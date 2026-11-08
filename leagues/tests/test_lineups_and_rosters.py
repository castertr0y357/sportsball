import json
from datetime import date, timedelta
from django.urls import reverse
from django.utils import timezone
from core.models import Church, Announcement
from users.models import CustomUser
from leagues.models import (
    League, Season, Team, SeasonRegistration, Game,
    LeagueVenue, PlayerDisciplinaryRecord, GameSportsmanshipRating,
    GameOfficialAssignment, GameLineupEntry
)
from stats.models import PlayerGameStat
from leagues.tests.base import BaseLeagueTestCase



class TestLineupsAndRostersCase(BaseLeagueTestCase):

    def test_create_team_view_works_for_coach_and_blocks_player(self):
        # Player should be redirected and blocked
        self.client.login(username="player_user", password="password123")
        resp = self.client.post(reverse('create_team', args=[self.season.id]), {
            'name': 'Unauthorized Team',
            'captain': self.player_user.id,
            'team_color': 'Red',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Team.objects.filter(name='Unauthorized Team').exists())

        # Coach should succeed
        self.client.login(username="coach_user", password="password123")
        resp_get = self.client.get(reverse('create_team', args=[self.season.id]))
        self.assertEqual(resp_get.status_code, 200)

        resp_post = self.client.post(reverse('create_team', args=[self.season.id]), {
            'name': 'Grace Warriors',
            'church': self.church.id,
            'captain': self.coach_user.id,
            'team_color': 'Silver',
        })
        self.assertEqual(resp_post.status_code, 302)
        created_team = Team.objects.get(name='Grace Warriors')
        self.assertEqual(created_team.season, self.season)
        self.assertIn(self.coach_user, created_team.players.all())


    def test_coach_team_invite_authenticated_user(self):
        self.client.login(username="player_user", password="password123")
        invite_code = self.team1.invite_code
        self.assertTrue(bool(invite_code))

        # GET confirms invitation page
        resp_get = self.client.get(reverse('join_team_invite', args=[invite_code]))
        self.assertEqual(resp_get.status_code, 200)
        self.assertContains(resp_get, self.team1.name)

        # POST accepts and joins roster
        resp_post = self.client.post(reverse('join_team_invite', args=[invite_code]))
        self.assertEqual(resp_post.status_code, 302)
        self.assertRedirects(resp_post, reverse('team_detail', args=[self.team1.id]))

        self.team1.refresh_from_db()
        self.assertIn(self.player_user, self.team1.players.all())
        reg = SeasonRegistration.objects.get(season=self.season, player=self.player_user)
        self.assertEqual(reg.status, 'approved')


    def test_coach_team_invite_unauthenticated_new_user(self):
        invite_code = self.team1.invite_code
        # 1. Visiting invite URL as guest redirects to register with ?invite=
        resp_guest = self.client.get(reverse('join_team_invite', args=[invite_code]))
        self.assertEqual(resp_guest.status_code, 302)
        self.assertIn(f"invite={invite_code}", resp_guest.url)

        # 2. Registering with invite param automatically rosters the user
        resp_reg = self.client.post(
            f"{reverse('register')}?invite={invite_code}",
            {
                'first_name': 'Sarah',
                'last_name': 'Connor',
                'email': 'sarah@resistance.org',
                'password1': 'SkynetDown2026!',
                'password2': 'SkynetDown2026!',
                'invite': invite_code,
            }
        )
        self.assertEqual(resp_reg.status_code, 302)
        self.assertRedirects(resp_reg, reverse('team_detail', args=[self.team1.id]))

        new_user = CustomUser.objects.get(email='sarah@resistance.org')
        self.team1.refresh_from_db()
        self.assertIn(new_user, self.team1.players.all())
        reg = SeasonRegistration.objects.get(season=self.season, player=new_user)
        self.assertEqual(reg.status, 'approved')


    def test_coach_cannot_score_unrelated_game(self):
        # Create game between team2 and team3 (neither has coach_user as captain)
        # Note: self.team1 captain is coach_user, self.team2 captain is admin_user
        unrelated_game = Game.objects.create(
            season=self.season,
            team1=self.team2,
            team2=self.team4,
            date=timezone.now(),
            location="Gym B",
            status="scheduled",
            game_type="regular",
        )

        # 1. coach_user (captain of team1) attempts to score unrelated game -> blocked
        self.client.login(username="coach_user", password="password123")
        resp_post = self.client.post(reverse('record_game_score', args=[unrelated_game.id]), {
            'team1_score': 10,
            'team2_score': 8,
            'status': 'completed',
        })
        self.assertEqual(resp_post.status_code, 302)
        unrelated_game.refresh_from_db()
        self.assertNotEqual(unrelated_game.status, 'completed')

        # 2. coach_user attempts Dugout action on unrelated game -> 403 Forbidden
        resp_ajax = self.client.post(
            reverse('dugout_action', args=[unrelated_game.id]),
            data='{"action": "single"}',
            content_type='application/json'
        )
        self.assertEqual(resp_ajax.status_code, 403)

        # 3. Participating team captain (admin_user for team2) can operate Dugout action
        self.client.login(username="admin_user", password="password123")
        resp_captain_ajax = self.client.post(
            reverse('dugout_action', args=[unrelated_game.id]),
            data='{"action": "single"}',
            content_type='application/json'
        )
        self.assertEqual(resp_captain_ajax.status_code, 200)

        # 4. Impartial referee can also operate Dugout action (clear lock from step 3)
        unrelated_game.active_scorer = None
        unrelated_game.save()
        ref = CustomUser.objects.create_user(
            username="ref_user",
            password="password123",
            role="referee",
        )
        self.client.login(username="ref_user", password="password123")
        resp_ref_ajax = self.client.post(
            reverse('dugout_action', args=[unrelated_game.id]),
            data='{"action": "walk"}',
            content_type='application/json'
        )
        self.assertEqual(resp_ref_ajax.status_code, 200)


    def test_assign_registration_scoping(self):
        reg = SeasonRegistration.objects.create(
            season=self.season,
            player=self.player_user,
            status='pending',
        )

        # coach_user is captain of team1. Cannot assign to team2!
        self.client.login(username="coach_user", password="password123")
        resp_bad = self.client.post(reverse('assign_registration', args=[reg.id]), {
            'action': 'approve',
            'team_id': self.team2.id,
        })
        self.assertEqual(resp_bad.status_code, 302)
        reg.refresh_from_db()
        self.assertNotEqual(reg.preferred_team, self.team2)

        # coach_user CAN assign to team1 (their own team)
        resp_good = self.client.post(reverse('assign_registration', args=[reg.id]), {
            'action': 'approve',
            'team_id': self.team1.id,
        })
        self.assertEqual(resp_good.status_code, 302)
        reg.refresh_from_db()
        self.assertEqual(reg.preferred_team, self.team1)
        self.assertIn(self.player_user, self.team1.players.all())

        # coach_user cannot toggle dues
        resp_dues_coach = self.client.post(reverse('assign_registration', args=[reg.id]), {
            'action': 'toggle_dues',
        })
        self.assertEqual(resp_dues_coach.status_code, 302)
        reg.refresh_from_db()
        self.assertFalse(reg.dues_paid)

        # admin_user CAN toggle dues
        self.client.login(username="admin_user", password="password123")
        resp_dues_admin = self.client.post(reverse('assign_registration', args=[reg.id]), {
            'action': 'toggle_dues',
        })
        self.assertEqual(resp_dues_admin.status_code, 302)
        reg.refresh_from_db()
        self.assertTrue(reg.dues_paid)


    def test_upcoming_game_lineup_builder_multi_position_and_rotations(self):
        # Add coach_user as player to team1
        self.team1.players.add(self.coach_user)
        # Create scheduled game
        game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now() + timedelta(days=3),
            location="Gym A",
            status="scheduled",
            game_type="regular",
        )
        game.ensure_lineups_initialized()

        # 1. Rival player (player_user is on team2) tries to access team1 lineup builder -> blocked
        self.team2.players.add(self.player_user)
        self.client.login(username="player_user", password="password123")
        resp_unauth = self.client.get(reverse('game_lineup_builder', args=[game.id, self.team1.id]))
        self.assertEqual(resp_unauth.status_code, 302)

        # 2. Coach of team1 accesses lineup builder -> 200 OK
        self.client.login(username="coach_user", password="password123")
        resp_get = self.client.get(reverse('game_lineup_builder', args=[game.id, self.team1.id]))
        self.assertEqual(resp_get.status_code, 200)
        self.assertContains(resp_get, "Batting Order &amp; Defensive Rotations")

        # 3. Coach saves multi-position and inning rotations
        entry = game.lineup_entries.filter(team=self.team1).first()
        self.assertIsNotNone(entry)

        resp_post = self.client.post(reverse('game_lineup_builder', args=[game.id, self.team1.id]), {
            'action': 'save_lineup',
            f'order_{entry.id}': 1,
            f'position_{entry.id}': 'SS / P',
            f'present_{entry.id}': '1',
            f'rotation_{entry.id}_1': 'SS',
            f'rotation_{entry.id}_2': 'SS',
            f'rotation_{entry.id}_3': 'P',
            f'rotation_{entry.id}_4': 'P',
        })
        self.assertEqual(resp_post.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.field_position, 'SS / P')
        self.assertEqual(entry.position_rotations.get('1'), 'SS')
        self.assertEqual(entry.position_rotations.get('3'), 'P')
        self.assertEqual(entry.get_position_for_inning(1), 'SS')
        self.assertEqual(entry.get_position_for_inning(3), 'P')
        self.assertEqual(entry.get_position_for_inning(7), 'SS / P')  # Fallback to field_position


    def test_game_rsvp_and_autofill_lineup(self):
        game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now() + timedelta(days=2),
            location="Diamond #1",
            status="scheduled",
            game_type="regular",
        )
        # Add player_user and a second player to team1
        self.team1.players.add(self.player_user)
        player2 = CustomUser.objects.create_user(username="player2", password="password123", role="player")
        self.team1.players.add(player2)
        game.ensure_lineups_initialized()

        # 1. player_user RSVPs 'yes' (I'm In)
        self.client.login(username="player_user", password="password123")
        resp_rsvp1 = self.client.post(
            reverse('game_rsvp', args=[game.id]),
            data=json.dumps({'response': 'yes', 'notes': 'Bringing the bats!'}),
            content_type='application/json'
        )
        self.assertEqual(resp_rsvp1.status_code, 200)
        self.assertEqual(resp_rsvp1.json()['response'], 'yes')

        # 2. player2 RSVPs 'no' (Can't Make It)
        self.client.login(username="player2", password="password123")
        resp_rsvp2 = self.client.post(
            reverse('game_rsvp', args=[game.id]),
            data=json.dumps({'response': 'no', 'notes': 'Out of town'}),
            content_type='application/json'
        )
        self.assertEqual(resp_rsvp2.status_code, 200)

        # 3. Check summary
        summary = game.get_team_rsvp_summary(self.team1)
        self.assertEqual(summary['yes'], 1)
        self.assertEqual(summary['no'], 1)

        # 4. Coach triggers autofill_rsvps -> confirmed player is at top, absent player benched
        self.client.login(username="coach_user", password="password123")
        resp_autofill = self.client.post(reverse('game_lineup_builder', args=[game.id, self.team1.id]), {
            'action': 'autofill_rsvps',
        })
        self.assertEqual(resp_autofill.status_code, 302)

        entry_yes = game.lineup_entries.get(team=self.team1, player=self.player_user)
        entry_no = game.lineup_entries.get(team=self.team1, player=player2)
        self.assertTrue(entry_yes.is_present)
        self.assertFalse(entry_no.is_present)
        self.assertLess(entry_yes.batting_order, entry_no.batting_order)


    def test_coach_roster_inline_update_and_drop_player(self):
        # Add coach_user and player_user to team1
        self.team1.players.add(self.coach_user, self.player_user)
        self.client.login(username="coach_user", password="password123")

        # 1. Update jersey and preferred position
        resp_update = self.client.post(reverse('manage_roster_player', args=[self.team1.id]), {
            'action': 'update_player',
            'player_id': self.player_user.id,
            'jersey_number': 42,
            'preferred_position': 'SS / P',
            'gender': 'M',
        })
        self.assertEqual(resp_update.status_code, 302)
        self.player_user.refresh_from_db()
        self.assertEqual(self.player_user.jersey_number, 42)
        self.assertEqual(self.player_user.preferred_position, 'SS / P')
        self.assertEqual(self.player_user.gender, 'M')

        # 2. Cannot drop captain
        resp_drop_cap = self.client.post(reverse('manage_roster_player', args=[self.team1.id]), {
            'action': 'remove_player',
            'player_id': self.coach_user.id,
        })
        self.assertTrue(self.team1.players.filter(id=self.coach_user.id).exists())

        # 3. Drop player_user
        resp_drop = self.client.post(reverse('manage_roster_player', args=[self.team1.id]), {
            'action': 'remove_player',
            'player_id': self.player_user.id,
        })
        self.assertFalse(self.team1.players.filter(id=self.player_user.id).exists())

        # 4. Unauthorized user cannot manage roster
        self.client.login(username="player_user", password="password123")
        self.team1.players.add(self.player_user)
        resp_unauth = self.client.post(reverse('manage_roster_player', args=[self.team1.id]), {
            'action': 'remove_player',
            'player_id': self.coach_user.id,
        })
        self.assertEqual(resp_unauth.status_code, 302)
        self.assertTrue(self.team1.players.filter(id=self.coach_user.id).exists())


    def test_coach_quick_add_church_member_to_roster(self):
        new_member = CustomUser.objects.create_user(
            username="church_member_tim",
            email="tim@gracefellowship.org",
            first_name="Tim",
            last_name="Keller",
            church=self.church
        )
        self.client.login(username="coach_user", password="password123")

        resp = self.client.post(reverse('manage_roster_player', args=[self.team1.id]), {
            'action': 'quick_add_player',
            'player_id': new_member.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self.team1.players.filter(id=new_member.id).exists())


    def test_lineup_builder_copy_last_game_and_default_templates(self):
        self.team1.players.add(self.coach_user)
        self.team1.players.add(self.player_user)
        self.client.login(username="coach_user", password="password123")

        # Game 1: set batting order and positions
        g1 = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now() - timedelta(days=7),
            location="Gym",
            status="completed"
        )
        g1.ensure_lineups_initialized()
        e1_coach = g1.lineup_entries.get(team=self.team1, player=self.coach_user)
        e1_coach.batting_order = 1
        e1_coach.field_position = "SS"
        e1_coach.save()

        e1_player = g1.lineup_entries.get(team=self.team1, player=self.player_user)
        e1_player.batting_order = 2
        e1_player.field_position = "1B"
        e1_player.save()

        # Save Game 1 lineup as master default
        resp_save_def = self.client.post(reverse('game_lineup_builder', args=[g1.id, self.team1.id]), {
            'action': 'save_as_default'
        })
        self.assertEqual(resp_save_def.status_code, 302)
        self.team1.refresh_from_db()
        self.assertIn('entries', self.team1.default_lineup)

        # Game 2: copy previous lineup
        g2 = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now() + timedelta(days=2),
            location="Gym",
            status="scheduled"
        )
        g2.ensure_lineups_initialized()

        resp_copy = self.client.post(reverse('game_lineup_builder', args=[g2.id, self.team1.id]), {
            'action': 'copy_previous_lineup'
        })
        self.assertEqual(resp_copy.status_code, 302)

        e2_coach = g2.lineup_entries.get(team=self.team1, player=self.coach_user)
        e2_player = g2.lineup_entries.get(team=self.team1, player=self.player_user)
        self.assertEqual(e2_coach.batting_order, 1)
        self.assertEqual(e2_coach.field_position, "SS")
        self.assertEqual(e2_player.batting_order, 2)
        self.assertEqual(e2_player.field_position, "1B")


    def test_coed_compliance_and_print_lineup_card(self):
        player_female = CustomUser.objects.create_user(
            username="sarah_player",
            email="sarah@gracefellowship.org",
            first_name="Sarah",
            gender="F",
            church=self.church
        )
        self.coach_user.gender = "M"
        self.coach_user.save()
        self.player_user.gender = "M"
        self.player_user.save()

        self.team1.players.add(self.coach_user, self.player_user, player_female)

        g = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now() + timedelta(days=2),
            location="Diamond #1",
            status="scheduled"
        )
        g.ensure_lineups_initialized()

        # Set order: coach (M) spot 1, player (M) spot 2 -> consecutive male notice
        e_coach = g.lineup_entries.get(team=self.team1, player=self.coach_user)
        e_coach.batting_order = 1
        e_coach.save()

        e_player = g.lineup_entries.get(team=self.team1, player=self.player_user)
        e_player.batting_order = 2
        e_player.save()

        self.client.login(username="coach_user", password="password123")
        resp_builder = self.client.get(reverse('game_lineup_builder', args=[g.id, self.team1.id]))
        self.assertEqual(resp_builder.status_code, 200)
        coed = resp_builder.context['coed_status']
        self.assertFalse(coed['is_alternating'])
        self.assertEqual(coed['consecutive_male_pairs'], [(1, 2)])

        # Test official printable lineup card
        resp_print = self.client.get(reverse('game_lineup_print', args=[g.id, self.team1.id]))
        self.assertEqual(resp_print.status_code, 200)
        self.assertContains(resp_print, "Official Starting Lineup")
        self.assertContains(resp_print, self.coach_user.display_name)


    def test_emergency_substitute_policy(self):
        """Verifies league-toggleable emergency substitute rules and playoff ringer prevention."""
        from users.models import CustomUser
        guest_sub = CustomUser.objects.create_user(
            username="guest_sub", email="guest@sportsball.local",
            password="sportsball123", first_name="Luke", last_name="Guest",
            role="player", waiver_signed=True
        )

        # 1. League disallows emergency subs by default
        self.league.allow_emergency_subs = False
        self.league.save()

        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Field A", status='scheduled', game_type='regular'
        )

        self.client.login(username="coach_user", password="password123")
        resp = self.client.post(reverse('game_lineup_builder', args=[game.id, self.team1.id]), {
            'action': 'add_emergency_sub',
            'sub_user_id': str(guest_sub.id),
            'consent_confirmed': '1'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(game.lineup_entries.filter(player=guest_sub).exists())

        # 2. Enable emergency subs for regular season
        self.league.allow_emergency_subs = True
        self.league.save()

        resp = self.client.post(reverse('game_lineup_builder', args=[game.id, self.team1.id]), {
            'action': 'add_emergency_sub',
            'sub_user_id': str(guest_sub.id),
            'consent_confirmed': '1'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(game.lineup_entries.filter(player=guest_sub, is_emergency_sub=True, sub_consented_by_opponent=True).exists())

        # 3. In playoff games, emergency subs are prohibited
        playoff_game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now() + timedelta(days=1), location="Field A", status='scheduled', game_type='playoff_final'
        )
        resp = self.client.post(reverse('game_lineup_builder', args=[playoff_game.id, self.team1.id]), {
            'action': 'add_emergency_sub',
            'sub_user_id': str(guest_sub.id),
            'consent_confirmed': '1'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(playoff_game.lineup_entries.filter(player=guest_sub).exists())


    def test_import_teams_across_seasons(self):
        self.client.login(username="admin_user", password="password123")
        target_season = Season.objects.create(
            league=self.league,
            name="Fall 2027 Fellowship Season",
            start_date=date.today() + timedelta(days=365),
            end_date=date.today() + timedelta(days=425),
        )

        resp = self.client.post(reverse('import_season_teams', args=[target_season.id]), {
            'confirm_import': '1',
            'source_season_id': str(self.season.id),
            'selected_teams': [self.team1.id, self.team2.id]
        })
        self.assertEqual(resp.status_code, 302)
        
        # Verify teams exist in target season
        imported_team_names = list(target_season.teams.values_list('name', flat=True))
        self.assertIn(self.team1.name, imported_team_names)
        self.assertIn(self.team2.name, imported_team_names)


    def test_walkup_audio_size_validation(self):
        from users.forms import ProfileForm
        from django.core.files.uploadedfile import SimpleUploadedFile
        # Mock file > 5MB
        oversized_data = b"x" * (6 * 1024 * 1024)
        mock_file = SimpleUploadedFile("big_song.mp3", oversized_data, content_type="audio/mpeg")

        form = ProfileForm(
            data={'first_name': 'Test', 'last_name': 'User', 'email': 'test@example.com'},
            files={'walkup_song_file': mock_file},
            instance=self.player_user
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Audio file too large", str(form.errors))


