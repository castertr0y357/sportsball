import json
from datetime import date, timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import Church, Announcement
from users.models import CustomUser
from leagues.models import League, Season, Team, SeasonRegistration, Game, LeagueVenue, PlayerDisciplinaryRecord, GameSportsmanshipRating
from stats.models import PlayerGameStat


class ChurchSportsLeaguesTestSuite(TestCase):
    def setUp(self):
        self.church = Church.objects.create(
            name="First Baptist Fellowship",
            denomination="Baptist",
            city="Greenville",
            state="SC",
        )
        self.admin_user = CustomUser.objects.create_user(
            username="admin_user",
            password="password123",
            role="admin",
            church=self.church,
        )
        self.coach_user = CustomUser.objects.create_user(
            username="coach_user",
            password="password123",
            role="coach",
            church=self.church,
        )
        self.player_user = CustomUser.objects.create_user(
            username="player_user",
            password="password123",
            role="player",
            church=self.church,
        )

        self.league = League.objects.create(
            name="Fellowship Basketball League",
            sport="basketball",
            description="Weekly church basketball",
            admin=self.admin_user,
        )
        self.season = Season.objects.create(
            league=self.league,
            name="Winter 2026",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=60),
            current=True,
            registration_open=True,
            registration_fee=25.00,
        )
        self.team1 = Team.objects.create(
            name="Eagles",
            league=self.league,
            season=self.season,
            church=self.church,
            captain=self.coach_user,
        )
        self.team2 = Team.objects.create(
            name="Lions",
            league=self.league,
            season=self.season,
            church=self.church,
            captain=self.admin_user,
        )
        self.team3 = Team.objects.create(
            name="Anchors",
            league=self.league,
            season=self.season,
            church=self.church,
            captain=self.coach_user,
        )
        self.team4 = Team.objects.create(
            name="Royals",
            league=self.league,
            season=self.season,
            church=self.church,
            captain=self.admin_user,
        )

    def test_public_and_dashboard_views(self):
        Announcement.objects.create(
            title="Rainout Alert",
            category="weather",
            content="Softball fields closed tonight.",
            is_urgent=True,
        )
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Rainout Alert")

        # Unauthenticated users cannot view partner church directory
        resp_guest_churches = self.client.get(reverse('church_list'))
        self.assertEqual(resp_guest_churches.status_code, 302)
        self.assertRedirects(resp_guest_churches, reverse('home'))

        # Overall / League admins can access partner church directory
        self.client.login(username="admin_user", password="password123")
        resp_admin_churches = self.client.get(reverse('church_list'))
        self.assertEqual(resp_admin_churches.status_code, 200)
        self.assertContains(resp_admin_churches, "First Baptist Fellowship")

    def test_waiver_signing_and_profile(self):
        self.client.login(username="player_user", password="password123")
        self.assertFalse(self.player_user.waiver_signed)

        # 1. Anti-Garbage Test: mismatched signature name should be rejected
        resp_bad = self.client.post(reverse('sign_waiver'), {
            'signature': 'Garbage Asdf Name',
            'agree': True,
        })
        self.assertEqual(resp_bad.status_code, 200)
        self.player_user.refresh_from_db()
        self.assertFalse(self.player_user.waiver_signed)

        # 2. Legitimate matching signature succeeds
        resp_good = self.client.post(reverse('sign_waiver'), {
            'signature': 'player_user',
            'agree': True,
        })
        self.assertEqual(resp_good.status_code, 302)
        self.player_user.refresh_from_db()
        self.assertTrue(self.player_user.waiver_signed)
        self.assertEqual(self.player_user.waiver_signature, 'player_user')

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

    def test_standings_calculation(self):
        Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now(),
            location="Gym A",
            status='completed',
            game_type='regular',
            team1_score=60,
            team2_score=50,
        )
        standings = self.season.get_standings()
        self.assertEqual(standings[0]['team'], self.team1)
        self.assertEqual(standings[0]['wins'], 1)
        self.assertEqual(standings[0]['point_diff'], 10)
        self.assertEqual(standings[0]['streak'], 'W1')

        team2_row = [r for r in standings if r['team'] == self.team2][0]
        self.assertEqual(team2_row['losses'], 1)
        self.assertEqual(team2_row['point_diff'], -10)
        self.assertEqual(team2_row['streak'], 'L1')

    def test_round_robin_schedule_generator(self):
        self.client.login(username="admin_user", password="password123")
        start_dt = (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT18:30')
        resp = self.client.post(reverse('generate_schedule', args=[self.season.id]), {
            'start_datetime': start_dt,
            'location': 'Fellowship Court 1',
            'double_round_robin': False,
            'clear_existing_scheduled': True,
        })
        self.assertEqual(resp.status_code, 302)
        # 4 teams in single round-robin = 6 games across 3 weeks
        self.assertEqual(self.season.games.filter(game_type='regular').count(), 6)

    def test_playoff_bracket_generation_and_advancement(self):
        self.client.login(username="admin_user", password="password123")
        resp = self.client.post(reverse('generate_playoffs', args=[self.season.id]))
        self.assertEqual(resp.status_code, 302)
        semis = list(self.season.games.filter(game_type='playoff_sf').order_by('id'))
        self.assertEqual(len(semis), 2)

        # Complete both semifinals
        semis[0].team1_score = 70
        semis[0].team2_score = 60
        semis[0].status = 'completed'
        semis[0].save()

        semis[1].team1_score = 55
        semis[1].team2_score = 62
        semis[1].status = 'completed'
        semis[1].save()

        resp_adv = self.client.post(reverse('advance_playoffs_to_final', args=[self.season.id]))
        self.assertEqual(resp_adv.status_code, 302)
        final_game = self.season.games.filter(game_type='playoff_final').first()
        self.assertIsNotNone(final_game)
        self.assertEqual(final_game.team1, semis[0].team1)
        self.assertEqual(final_game.team2, semis[1].team2)

    def test_score_entry_and_stat_leaderboard(self):
        game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now(),
            location="Gym A",
            status='scheduled',
        )
        self.team1.players.add(self.player_user)
        self.client.login(username="coach_user", password="password123")

        # Record score
        self.client.post(reverse('record_game_score', args=[game.id]), {
            'team1_score': 58,
            'team2_score': 54,
            'status': 'completed',
            'notes': 'Great fellowship game',
        })
        game.refresh_from_db()
        # Coach submission enters pending confirmation until verified
        self.assertEqual(game.status, 'pending_confirmation')
        game.confirm_score(self.admin_user)
        self.assertEqual(game.status, 'completed')
        self.assertEqual(game.winner, self.team1)

        # Record player stat
        self.client.post(reverse('add_game_stat', args=[game.id]), {
            'player': self.player_user.id,
            'team': self.team1.id,
            'category': 'Points',
            'value': 26,
        })
        self.assertEqual(PlayerGameStat.objects.filter(player=self.player_user, category='Points').count(), 1)

        # Check leaderboard
        resp_lb = self.client.get(reverse('leaderboard') + f"?season={self.season.id}&category=Points")
        self.assertEqual(resp_lb.status_code, 200)
        self.assertContains(resp_lb, "player_user")
        self.assertContains(resp_lb, "26")

    def test_dugout_console_lineup_attendance_and_walkup_rotation(self):
        p2 = CustomUser.objects.create_user(
            username="batter_two",
            password="password123",
            role="player",
            walkup_song_title="Batter Two Anthem",
            walkup_start_seconds=5,
            walkup_duration_seconds=10,
        )
        p3 = CustomUser.objects.create_user(
            username="batter_three",
            password="password123",
            role="player",
            walkup_song_title="Batter Three Riff",
        )
        # Away team (team2) bats in Top of Inning 1
        self.team2.players.add(self.player_user, p2, p3)

        game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now(),
            location="Diamond 1",
            status='scheduled',
        )

        self.client.login(username="coach_user", password="password123")
        resp_console = self.client.get(reverse('dugout_console', args=[game.id]))
        self.assertEqual(resp_console.status_code, 200)
        game.refresh_from_db()
        self.assertEqual(game.current_batter, self.player_user)

        # Mark p2 as absent via 1-tap attendance check-in so they are skipped
        p2_entry = game.lineup_entries.get(team=self.team2, player=p2)
        resp_att = self.client.post(
            reverse('dugout_action', args=[game.id]),
            data={'action': 'toggle_attendance', 'entry_id': p2_entry.id},
            content_type='application/json',
        )
        self.assertEqual(resp_att.status_code, 200)
        p2_entry.refresh_from_db()
        self.assertFalse(p2_entry.is_present)

        # Trigger Next Batter -> should skip absent p2 and land on p3 with trigger_walkup=True
        resp_next = self.client.post(
            reverse('dugout_action', args=[game.id]),
            data={'action': 'next_batter'},
            content_type='application/json',
        )
        self.assertEqual(resp_next.status_code, 200)
        payload = resp_next.json()
        self.assertTrue(payload['trigger_walkup'])
        self.assertEqual(payload['current_batter']['name'], p3.display_name)
        self.assertEqual(payload['current_batter']['walkup_song_title'], "Batter Three Riff")

        # Record 3 outs and verify half-inning automatically flips to Bottom 1 and clears bases
        self.client.post(reverse('dugout_action', args=[game.id]), data={'action': 'single'}, content_type='application/json')
        game.refresh_from_db()
        self.assertTrue(game.runner_on_first)
        self.assertEqual(game.team2_hits, 1)

        for _ in range(3):
            self.client.post(reverse('dugout_action', args=[game.id]), data={'action': 'out'}, content_type='application/json')

        game.refresh_from_db()
        self.assertEqual(game.inning_half, 'bottom')
        self.assertEqual(game.current_inning, 1)
        self.assertEqual(game.outs, 0)
        self.assertFalse(game.runner_on_first)

        # Verify public GameCast & live-state endpoints
        resp_gc = self.client.get(reverse('gamecast', args=[game.id]))
        self.assertEqual(resp_gc.status_code, 200)
        resp_state = self.client.get(reverse('game_live_state', args=[game.id]))
        self.assertEqual(resp_state.status_code, 200)
        self.assertEqual(resp_state.json()['inning_half'], 'bottom')

    def test_pwa_manifest_and_offline_batch_sync(self):
        # 1. PWA ServiceWorker route check
        resp_sw = self.client.get('/sw.js')
        self.assertEqual(resp_sw.status_code, 200)
        self.assertIn('csl-dugout-v1', resp_sw.content.decode('utf-8'))

        # 2. Public No-Login Browsing Verification
        self.client.logout()
        resp_public_season = self.client.get(reverse('season_detail', args=[self.season.id]))
        self.assertEqual(resp_public_season.status_code, 200)
        self.assertContains(resp_public_season, "Season Standings")

        resp_public_leagues = self.client.get(reverse('league_list'))
        self.assertEqual(resp_public_leagues.status_code, 200)

        # 3. Batch Sync Endpoint test
        game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now(),
            location="Diamond 2",
            status='scheduled',
        )
        self.team2.players.add(self.player_user)
        self.client.login(username="coach_user", password="password123")

        # Simulate offline actions queued by mobile browser: single, run_plus, out
        queued_actions = [
            {'action': 'single', 'extra': {}},
            {'action': 'run_plus', 'team': 'team2'},
            {'action': 'out', 'extra': {}},
        ]
        resp_sync = self.client.post(
            reverse('dugout_batch_sync', args=[game.id]),
            data={'actions': queued_actions},
            content_type='application/json',
        )
        self.assertEqual(resp_sync.status_code, 200)
        payload = resp_sync.json()
        self.assertEqual(payload['synced_count'], 3)
        self.assertEqual(payload['team2_score'], 1)
        self.assertEqual(payload['team2_hits'], 1)
        self.assertEqual(payload['outs'], 1)

        game.refresh_from_db()
        self.assertEqual(game.team2_score, 1)
        self.assertEqual(game.team2_hits, 1)
        self.assertEqual(game.outs, 1)

    def test_practice_sandbox_requires_login(self):
        # 1. Unregistered guest redirected to login
        resp_guest = self.client.get(reverse('practice_sandbox'))
        self.assertEqual(resp_guest.status_code, 302)
        self.assertIn(reverse('login'), resp_guest.url)

        # 2. Logged in volunteer has access
        self.client.login(username="coach_user", password="password123")
        resp_member = self.client.get(reverse('practice_sandbox'))
        self.assertEqual(resp_member.status_code, 200)


    def test_email_only_registration(self):
        resp = self.client.post(reverse('register'), {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john.doe@fellowship.org',
            'password1': 'Secret12345!',
            'password2': 'Secret12345!',
        })
        self.assertEqual(resp.status_code, 302)
        user = CustomUser.objects.get(email='john.doe@fellowship.org')
        self.assertEqual(user.first_name, 'John')
        self.assertEqual(user.last_name, 'Doe')
        self.assertEqual(user.display_name, 'John Doe')

        # Verify email login (both exact and case-insensitive)
        self.client.logout()
        logged_in = self.client.login(username='john.doe@fellowship.org', password='Secret12345!')
        self.assertTrue(logged_in)
        self.client.logout()
        logged_in_upper = self.client.login(username='JOHN.DOE@FELLOWSHIP.ORG', password='Secret12345!')
        self.assertTrue(logged_in_upper)

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

    def test_seeded_test_accounts_email_logins(self):
        from django.core.management import call_command
        call_command('create_test_users')

        test_accounts = [
            ('commissioner@sportsball.local', 'sportsball123', 'Paul Andrews'),
            ('coach.grace@sportsball.local', 'sportsball123', 'Caleb Brooks'),
            ('coach.calvary@sportsball.local', 'sportsball123', 'David Miller'),
            ('umpire.bob@sportsball.local', 'sportsball123', 'Bob Jenkins'),
            ('player.josh@sportsball.local', 'sportsball123', 'Josh Peterson'),
            ('freeagent.eli@sportsball.local', 'sportsball123', 'Eli Walker'),
            ('unverified@sportsball.local', 'sportsball123', 'Tommy Test'),
        ]

        for email, pwd, expected_name in test_accounts:
            self.client.logout()
            logged_in = self.client.login(username=email, password=pwd)
            self.assertTrue(logged_in, f"Failed to login with email: {email}")

        # Test testing portal shows all accounts as created with their emails
        resp = self.client.get(reverse('test_users_portal'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Not Created")
        self.assertContains(resp, "coach.grace@sportsball.local")
        self.assertContains(resp, "commissioner@sportsball.local")

        # Test 1-click switch by username or email
        switch_resp = self.client.post(reverse('quick_switch_test_user', args=['coach_grace']))
        self.assertEqual(switch_resp.status_code, 302)
        switch_email_resp = self.client.post(reverse('quick_switch_test_user', args=['coach.calvary@sportsball.local']))
        self.assertEqual(switch_email_resp.status_code, 302)

    def test_church_directory_access_control_and_my_church(self):
        # 1. Unauthenticated guest -> redirects to home
        resp_guest = self.client.get(reverse('church_list'))
        self.assertEqual(resp_guest.status_code, 302)
        self.assertRedirects(resp_guest, reverse('home'))

        # 2. Regular player with home church visiting church_list -> redirected to my_church -> church_detail
        self.client.login(username="player_user", password="password123")
        resp_player = self.client.get(reverse('church_list'))
        self.assertEqual(resp_player.status_code, 302)
        self.assertRedirects(resp_player, reverse('my_church'), target_status_code=302)

        resp_my_church = self.client.get(reverse('my_church'))
        self.assertEqual(resp_my_church.status_code, 302)
        self.assertRedirects(resp_my_church, reverse('church_detail', args=[self.church.id]))

        # 3. Regular player with NO church gets church selector
        self.player_user.church = None
        self.player_user.save(update_fields=['church'])
        resp_select = self.client.get(reverse('my_church'))
        self.assertEqual(resp_select.status_code, 200)
        self.assertContains(resp_select, "Connect to Your Church")

    def test_church_commissioner_creates_team_and_designates_captain(self):
        # Assign coach_user as Church Commissioner for First Baptist Fellowship
        self.church.commissioner = self.coach_user
        self.coach_user.role = 'church_admin'
        self.coach_user.save()
        self.church.save()

        self.client.login(username="coach_user", password="password123")
        self.assertTrue(self.coach_user.is_church_commissioner)

        # Church Commissioner creates team for their church and designates player_user as Captain
        resp_create = self.client.post(
            reverse('create_team', args=[self.season.id]),
            {
                'name': 'Grace Warriors',
                'church': self.church.id,
                'captain': self.player_user.id,
                'team_color': 'Navy Blue',
            }
        )
        self.assertEqual(resp_create.status_code, 302)

        warriors = Team.objects.get(name='Grace Warriors', season=self.season)
        self.assertEqual(warriors.church, self.church)
        self.assertEqual(warriors.captain, self.player_user)
        self.assertIn(self.player_user, warriors.players.all())

        # Verify season registration auto-created for designated captain
        reg = SeasonRegistration.objects.get(season=self.season, player=self.player_user)
        self.assertEqual(reg.status, 'approved')

    def test_overall_commissioner_assigns_church_leader_and_dues(self):
        self.client.login(username="admin_user", password="password123")

        # Assign coach_user as Church Commissioner
        resp_assign = self.client.post(
            reverse('assign_church_commissioner', args=[self.church.id]),
            {'commissioner_id': self.coach_user.id}
        )
        self.assertEqual(resp_assign.status_code, 302)
        self.church.refresh_from_db()
        self.assertEqual(self.church.commissioner, self.coach_user)

        # Toggle dues to paid
        self.assertFalse(self.church.dues_paid)
        resp_dues = self.client.post(reverse('toggle_church_dues', args=[self.church.id]))
        self.assertEqual(resp_dues.status_code, 302)
        self.church.refresh_from_db()
        self.assertTrue(self.church.dues_paid)

    def test_waiver_visibility_restricted_to_captain_and_above(self):
        # Add player_user to team1
        self.team1.players.add(self.player_user)

        # 1. Regular player visits team_detail: Waiver column should NOT appear
        self.client.login(username="player_user", password="password123")
        resp_team_player = self.client.get(reverse('team_detail', args=[self.team1.id]))
        self.assertEqual(resp_team_player.status_code, 200)
        self.assertNotContains(resp_team_player, "<th>Waiver</th>")

        # 2. Regular player visits church_detail: Waiver column should NOT appear
        resp_church_player = self.client.get(reverse('church_detail', args=[self.church.id]))
        self.assertEqual(resp_church_player.status_code, 200)
        self.assertNotContains(resp_church_player, "<th>Waiver</th>")

        # 3. Team captain (coach_user) visits team_detail for team1: Waiver column SHOULD appear
        self.client.login(username="coach_user", password="password123")
        resp_team_captain = self.client.get(reverse('team_detail', args=[self.team1.id]))
        self.assertEqual(resp_team_captain.status_code, 200)
        self.assertContains(resp_team_captain, "<th>Waiver</th>")

        # 4. Overall commissioner (admin_user) visits church_detail: Waiver column SHOULD appear
        self.client.login(username="admin_user", password="password123")
        resp_church_admin = self.client.get(reverse('church_detail', args=[self.church.id]))
        self.assertEqual(resp_church_admin.status_code, 200)
        self.assertContains(resp_church_admin, "<th>Waiver</th>")

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

    def test_create_game_restricted_to_league_commissioner(self):
        # coach_user is not league commissioner -> blocked
        self.client.login(username="coach_user", password="password123")
        resp_coach = self.client.post(reverse('create_game', args=[self.season.id]), {
            'team1': self.team1.id,
            'team2': self.team2.id,
            'date': (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT18:30'),
            'location': 'Gym A',
            'game_type': 'regular',
            'week_number': 1,
            'status': 'scheduled',
        })
        self.assertEqual(resp_coach.status_code, 302)
        self.assertFalse(Game.objects.filter(location='Gym A', week_number=1).exists())

        # admin_user is league commissioner -> succeeds
        self.client.login(username="admin_user", password="password123")
        resp_admin = self.client.post(reverse('create_game', args=[self.season.id]), {
            'team1': self.team1.id,
            'team2': self.team2.id,
            'date': (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT18:30'),
            'location': 'Gym A',
            'game_type': 'regular',
            'week_number': 1,
            'status': 'scheduled',
        })
        self.assertEqual(resp_admin.status_code, 302)
        self.assertTrue(Game.objects.filter(location='Gym A', week_number=1).exists())

    def test_church_members_and_dues_privacy(self):
        church2 = Church.objects.create(name="Calvary Baptist", city="Greenville", state="SC")
        other_player = CustomUser.objects.create_user(
            username="other_player",
            password="password123",
            role="player",
            church=church2,
        )

        # 1. other_player from church2 viewing church1: member directory and dues are HIDDEN
        self.client.login(username="other_player", password="password123")
        resp_out = self.client.get(reverse('church_detail', args=[self.church.id]))
        self.assertEqual(resp_out.status_code, 200)
        self.assertNotContains(resp_out, "Congregation Athletes &amp; Members")
        self.assertContains(resp_out, "Internal congregation member directory is private")
        self.assertNotContains(resp_out, "League Dues")

        # 2. player_user (belongs to church1) viewing church1: members VISIBLE, but dues and waivers HIDDEN
        self.client.login(username="player_user", password="password123")
        resp_in = self.client.get(reverse('church_detail', args=[self.church.id]))
        self.assertEqual(resp_in.status_code, 200)
        self.assertContains(resp_in, "Congregation Athletes &amp; Members")
        self.assertNotContains(resp_in, "<th>Waiver</th>")
        self.assertNotContains(resp_in, "League Dues")

        # 3. admin_user (overall commissioner) viewing church1: members, waivers, and dues VISIBLE
        self.client.login(username="admin_user", password="password123")
        resp_adm = self.client.get(reverse('church_detail', args=[self.church.id]))
        self.assertEqual(resp_adm.status_code, 200)
        self.assertContains(resp_adm, "Congregation Athletes &amp; Members")
        self.assertContains(resp_adm, "<th>Waiver</th>")
        self.assertContains(resp_adm, "Dues Pending")

    def test_profile_waiver_privacy(self):
        # player_user has signed waiver
        self.player_user.waiver_signed = True
        self.player_user.save()

        # other_player views player_user profile -> Waiver Signed is NOT shown
        other = CustomUser.objects.create_user(username="viewer", password="password123", role="player")
        self.client.login(username="viewer", password="password123")
        resp_view = self.client.get(reverse('player_detail', args=[self.player_user.id]))
        self.assertEqual(resp_view.status_code, 200)
        self.assertNotContains(resp_view, "Waiver Signed")

        # player_user views own profile -> Waiver Signed IS shown
        self.client.login(username="player_user", password="password123")
        resp_self = self.client.get(reverse('profile'))
        self.assertEqual(resp_self.status_code, 200)
        self.assertContains(resp_self, "Waiver Signed")

    def test_free_agent_requires_login(self):
        # Unauthenticated request redirects to login
        resp = self.client.get(reverse('free_agent_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp.url)

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

    def test_coach_cannot_post_urgent_announcement(self):
        self.client.login(username="coach_user", password="password123")
        resp = self.client.post(reverse('create_announcement'), {
            'title': 'Coach Announcement',
            'category': 'general',
            'content': 'Practice moved to 7pm.',
            'league': self.league.id,
            'is_urgent': True,
        })
        self.assertEqual(resp.status_code, 302)
        ann = Announcement.objects.get(title='Coach Announcement')
        self.assertFalse(ann.is_urgent)  # Forced to False by permission enforcement

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

    def test_church_invite_onboarding_and_zero_step_waiver(self):
        # 1. Test church invite link
        self.assertTrue(bool(self.church.invite_code))
        invite_url = reverse('join_church_invite', args=[self.church.invite_code])

        # New user visits invite URL -> redirects to register with ?church_invite
        resp_anon = self.client.get(invite_url)
        self.assertEqual(resp_anon.status_code, 302)
        self.assertIn(f'church_invite={self.church.invite_code}', resp_anon.url)

        # Register user with church_invite and agree_waiver
        resp_reg = self.client.post(reverse('register'), {
            'first_name': 'Pastor',
            'last_name': 'Mark',
            'email': 'pastor.mark@gracefellowship.org',
            'password1': 'sportsball123',
            'password2': 'sportsball123',
            'agree_waiver': 'on',
            'church_invite': self.church.invite_code,
        }, follow=True)
        self.assertEqual(resp_reg.status_code, 200)

        new_user = CustomUser.objects.get(email='pastor.mark@gracefellowship.org')
        self.assertTrue(new_user.waiver_signed)
        self.church.refresh_from_db()
        self.assertEqual(self.church.commissioner, new_user)
        self.assertEqual(new_user.role, 'church_admin')

    def test_smart_multi_slot_schedule_generation(self):
        self.client.login(username="admin_user", password="password123")
        tomorrow = timezone.localdate() + timedelta(days=1)

        # 1. Test preview mode (no DB writes)
        resp_preview = self.client.post(reverse('generate_schedule', args=[self.season.id]), {
            'action': 'preview',
            'start_date': tomorrow.strftime('%Y-%m-%d'),
            'game_days': ['1', '3'],
            'time_slots': '18:30, 19:45',
            'venues': 'Court 1\nCourt 2',
            'protect_wednesdays': True,
            'protect_sunday_mornings': True,
            'double_round_robin': False,
            'add_weather_buffer': True,
            'clear_existing_scheduled': True,
        })
        self.assertEqual(resp_preview.status_code, 200)
        self.assertIsNotNone(resp_preview.context['preview_games'])
        self.assertEqual(len(resp_preview.context['preview_games']), 6)
        self.assertEqual(self.season.games.filter(game_type='regular').count(), 0)

        # 2. Test generate mode (commits to DB)
        resp_generate = self.client.post(reverse('generate_schedule', args=[self.season.id]), {
            'action': 'generate',
            'start_date': tomorrow.strftime('%Y-%m-%d'),
            'game_days': ['1', '3'],
            'time_slots': '18:30, 19:45',
            'venues': 'Court 1\nCourt 2',
            'protect_wednesdays': True,
            'protect_sunday_mornings': True,
            'double_round_robin': False,
            'add_weather_buffer': True,
            'clear_existing_scheduled': True,
        })
        self.assertEqual(resp_generate.status_code, 302)
        self.assertEqual(self.season.games.filter(game_type='regular').count(), 6)

        self.season.refresh_from_db()
        self.assertTrue(self.season.has_weather_buffer_week)
        self.assertIn('game_days', self.season.schedule_config)
        self.assertEqual(self.season.schedule_config['game_days'], [1, 3])

    def test_ics_calendar_feed_export(self):
        # Create a sample game
        game_dt = timezone.now() + timedelta(days=3)
        game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=game_dt,
            location="Gym Court 1",
            status="scheduled",
            game_type="regular"
        )

        # 1. Team calendar feed
        resp_team = self.client.get(reverse('team_calendar_ics', args=[self.team1.id]))
        self.assertEqual(resp_team.status_code, 200)
        self.assertIn('text/calendar', resp_team['Content-Type'])
        content_str = resp_team.content.decode('utf-8')
        self.assertIn('BEGIN:VCALENDAR', content_str)
        self.assertIn('BEGIN:VEVENT', content_str)
        self.assertIn('Gym Court 1', content_str)
        self.assertIn(f'{self.team1.name} vs {self.team2.name}', content_str)

        # 2. Season calendar feed
        resp_season = self.client.get(reverse('season_calendar_ics', args=[self.season.id]))
        self.assertEqual(resp_season.status_code, 200)
        self.assertIn('text/calendar', resp_season['Content-Type'])
        self.assertIn('BEGIN:VCALENDAR', resp_season.content.decode('utf-8'))

        # 3. User calendar feed (anonymous forbidden)
        resp_anon = self.client.get(reverse('user_calendar_ics'))
        self.assertEqual(resp_anon.status_code, 403)

        # User calendar feed (authenticated player)
        self.team1.players.add(self.player_user)
        self.client.login(username="player_user", password="password123")
        resp_user = self.client.get(reverse('user_calendar_ics'))
        self.assertEqual(resp_user.status_code, 200)
        self.assertIn('text/calendar', resp_user['Content-Type'])
        self.assertIn(self.team1.name, resp_user.content.decode('utf-8'))

    def test_rainout_today_and_auto_makeup(self):
        today = timezone.localdate()
        today_dt = timezone.now()
        game_today = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=today_dt,
            location="Diamond #1",
            status="scheduled",
            game_type="regular",
            week_number=1
        )

        # Non-commissioner cannot rain out
        self.client.login(username="player_user", password="password123")
        resp_denied = self.client.post(reverse('rainout_today_games', args=[self.season.id]))
        self.assertEqual(resp_denied.status_code, 302)
        game_today.refresh_from_db()
        self.assertEqual(game_today.status, 'scheduled')
        self.assertEqual(game_today.week_number, 1)

        # Commissioner rains out today -> auto moves to makeup week
        self.client.login(username="admin_user", password="password123")
        resp_rainout = self.client.post(reverse('rainout_today_games', args=[self.season.id]), {
            'action': 'reschedule_makeup',
            'date': today.strftime('%Y-%m-%d'),
        })
        self.assertEqual(resp_rainout.status_code, 302)

        game_today.refresh_from_db()
        self.assertEqual(game_today.status, 'scheduled')
        self.assertEqual(game_today.week_number, 2)
        self.assertGreater(game_today.date, today_dt)
        self.assertIn("Rescheduled from rainout", game_today.notes)

    def test_schedule_grid_and_swap_game_slots(self):
        g1 = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now() + timedelta(days=2),
            location="Court 1",
            status="scheduled",
            game_type="regular",
            week_number=1
        )
        g2 = Game.objects.create(
            season=self.season,
            team1=self.team3,
            team2=self.team4,
            date=timezone.now() + timedelta(days=5),
            location="Court 2",
            status="scheduled",
            game_type="regular",
            week_number=2
        )

        # Schedule grid view
        resp_grid = self.client.get(reverse('schedule_grid', args=[self.season.id]))
        self.assertEqual(resp_grid.status_code, 200)
        self.assertContains(resp_grid, "Court 1")
        self.assertContains(resp_grid, "Court 2")

        # Non-commissioner slot swap forbidden/redirected
        self.client.login(username="player_user", password="password123")
        self.client.post(reverse('swap_game_slots', args=[self.season.id]), {
            'game1_id': g1.id,
            'game2_id': g2.id,
        })
        g1.refresh_from_db()
        self.assertEqual(g1.location, "Court 1")

        # Commissioner swaps slots
        self.client.login(username="admin_user", password="password123")
        resp_swap = self.client.post(reverse('swap_game_slots', args=[self.season.id]), {
            'game1_id': g1.id,
            'game2_id': g2.id,
        })
        self.assertEqual(resp_swap.status_code, 302)

        g1.refresh_from_db()
        g2.refresh_from_db()
        self.assertEqual(g1.location, "Court 2")
        self.assertEqual(g2.location, "Court 1")
        self.assertEqual(g1.week_number, 2)
        self.assertEqual(g2.week_number, 1)

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

    def test_dugout_live_in_game_substitution(self):
        player_sub = CustomUser.objects.create_user(
            username="sub_player",
            email="sub@gracefellowship.org",
            first_name="Marcus",
            last_name="Sub",
            jersey_number=99,
            church=self.church
        )
        self.team1.players.add(self.coach_user, player_sub)

        game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now(),
            location="Diamond #2",
            status="in_progress",
            current_inning=2
        )
        game.ensure_lineups_initialized()

        e_coach = game.lineup_entries.get(team=self.team1, player=self.coach_user)
        e_coach.batting_order = 1
        e_coach.field_position = "Shortstop"
        e_coach.is_present = True
        e_coach.save()

        e_sub = game.lineup_entries.get(team=self.team1, player=player_sub)
        e_sub.batting_order = 2
        e_sub.field_position = "Bench"
        e_sub.is_present = False
        e_sub.save()

        game.current_batter = self.coach_user
        game.save()

        # Coach substitutes Marcus in for Coach
        self.client.login(username="coach_user", password="password123")
        resp = self.client.post(reverse('dugout_action', args=[game.id]), json.dumps({
            'action': 'substitute_player',
            'out_entry_id': e_coach.id,
            'in_entry_id': e_sub.id,
        }), content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        e_coach.refresh_from_db()
        e_sub.refresh_from_db()
        game.refresh_from_db()

        self.assertFalse(e_coach.is_present)
        self.assertTrue(e_sub.is_present)
        self.assertEqual(e_sub.batting_order, 1)
        self.assertEqual(e_sub.field_position, "Shortstop")
        self.assertEqual(game.current_batter, player_sub)


    def test_officials_hub_budget_and_pool_management(self):
        # Create referee user
        ref_user = CustomUser.objects.create_user(
            username="ref_tom",
            password="password123",
            role="referee",
            first_name="Tom",
            last_name="Referee",
            church=self.church
        )
        game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now() + timedelta(days=2),
            location="Court A"
        )

        # 1. League Admin logs into Officials Hub and adjusts budget
        self.client.login(username="admin_user", password="password123")
        resp_budget = self.client.post(reverse('officials_hub', args=[self.season.id]), {
            'action': 'update_budget',
            'officials_budget': '600.00',
            'official_default_pay': '40.00',
        })
        self.assertEqual(resp_budget.status_code, 302)
        self.season.refresh_from_db()
        self.assertEqual(float(self.season.officials_budget), 600.00)
        self.assertEqual(float(self.season.official_default_pay), 40.00)

        # 2. Add ref_tom to the officials pool
        resp_pool = self.client.post(reverse('officials_hub', args=[self.season.id]), {
            'action': 'add_pool_member',
            'user_id': ref_user.id,
        })
        self.assertEqual(resp_pool.status_code, 302)
        self.assertIn(ref_user, self.season.officials_pool.all())

        # 3. Assign ref_tom as Head Referee for game
        resp_assign = self.client.post(reverse('officials_hub', args=[self.season.id]), {
            'action': 'assign_official',
            'game_id': game.id,
            'official_id': ref_user.id,
            'role': 'head_ref',
            'pay_amount': '40.00',
        })
        self.assertEqual(resp_assign.status_code, 302)

        from leagues.models import GameOfficialAssignment
        assignment = GameOfficialAssignment.objects.get(game=game, official=ref_user, role='head_ref')
        self.assertEqual(assignment.status, 'assigned')
        self.assertEqual(assignment.pay_status, 'unpaid')
        self.assertEqual(float(assignment.pay_amount), 40.00)

        # 4. Check Budget Ledger Summary
        summary = self.season.get_officials_budget_summary()
        self.assertEqual(summary['budget'], 600.00)
        self.assertEqual(summary['allocated'], 40.00)
        self.assertEqual(summary['owed'], 40.00)
        self.assertEqual(summary['paid'], 0.00)
        self.assertEqual(summary['remaining'], 560.00)

        # 5. Mark stipend as paid
        resp_pay = self.client.post(reverse('officials_hub', args=[self.season.id]), {
            'action': 'toggle_pay_status',
            'assignment_id': assignment.id,
        })
        self.assertEqual(resp_pay.status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.pay_status, 'paid')
        summary2 = self.season.get_officials_budget_summary()
        self.assertEqual(summary2['paid'], 40.00)
        self.assertEqual(summary2['owed'], 0.00)

        # 6. Least Privilege: Regular player cannot access officials hub
        self.client.login(username="player_user", password="password123")
        resp_forbidden = self.client.get(reverse('officials_hub', args=[self.season.id]))
        self.assertEqual(resp_forbidden.status_code, 302)

    def test_official_1tap_confirm_and_sub_request_flow(self):
        from leagues.models import GameOfficialAssignment
        ref1 = CustomUser.objects.create_user(
            username="ref1", password="password123", role="referee", first_name="Ref", last_name="One"
        )
        ref2 = CustomUser.objects.create_user(
            username="ref2", password="password123", role="referee", first_name="Ref", last_name="Two"
        )
        self.season.officials_pool.add(ref1, ref2)

        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now() + timedelta(days=3), location="Field 1"
        )
        assignment = GameOfficialAssignment.objects.create(
            game=game, official=ref1, role='head_ref', pay_amount=30.00, status='assigned'
        )

        # 1. ref1 confirms
        self.client.login(username="ref1", password="password123")
        resp_confirm = self.client.post(reverse('respond_official_assignment', args=[assignment.id]), {
            'action': 'confirm'
        })
        self.assertEqual(resp_confirm.status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, 'confirmed')

        # 2. ref1 needs a sub ('Can't Make It')
        resp_sub = self.client.post(reverse('respond_official_assignment', args=[assignment.id]), {
            'action': 'request_sub',
            'notes': 'Family emergency',
        })
        self.assertEqual(resp_sub.status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, 'declined')
        self.assertEqual(assignment.notes, 'Family emergency')

        # 3. ref2 claims the open assignment
        self.client.login(username="ref2", password="password123")
        resp_claim = self.client.post(reverse('claim_official_assignment', args=[assignment.id]))
        self.assertEqual(resp_claim.status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.official, ref2)
        self.assertEqual(assignment.status, 'confirmed')
        self.assertIn("Covered by Ref Two", assignment.notes)

    def test_league_commissioner_1tap_team_dues_toggle(self):
        self.assertFalse(self.team1.dues_paid)

        # 1. League Commissioner toggles dues
        self.client.login(username="admin_user", password="password123")
        resp = self.client.post(reverse('toggle_team_dues', args=[self.team1.id]))
        self.assertEqual(resp.status_code, 302)
        self.team1.refresh_from_db()
        self.assertTrue(self.team1.dues_paid)

        # 2. Toggle back to unpaid
        resp2 = self.client.post(reverse('toggle_team_dues', args=[self.team1.id]))
        self.assertEqual(resp2.status_code, 302)
        self.team1.refresh_from_db()
        self.assertFalse(self.team1.dues_paid)

        # 3. Regular player blocked (Least Privilege)
        self.client.login(username="player_user", password="password123")
        resp_block = self.client.post(reverse('toggle_team_dues', args=[self.team1.id]))
        self.assertEqual(resp_block.status_code, 302)
        self.team1.refresh_from_db()
        self.assertFalse(self.team1.dues_paid)

    def test_free_agent_sub_availability_toggle_and_least_privilege(self):
        self.assertFalse(self.player_user.is_sub_available)
        self.client.login(username="player_user", password="password123")

        # Toggle on
        resp = self.client.post(reverse('toggle_sub_availability'))
        self.assertEqual(resp.status_code, 302)
        self.player_user.refresh_from_db()
        self.assertTrue(self.player_user.is_sub_available)

        # 1. Least Privilege: Player is blocked from viewing free agent pool & sidebar link is hidden
        self.player_user.is_free_agent = True
        self.player_user.save()
        resp_player = self.client.get(reverse('free_agent_list'))
        self.assertEqual(resp_player.status_code, 302)  # redirected to home

        resp_home = self.client.get(reverse('home'))
        self.assertNotContains(resp_home, reverse('free_agent_list'))

        # 2. Coaches & above can view free agents pool and see the sub beacon
        self.client.login(username="coach_user", password="password123")
        resp_coach = self.client.get(reverse('free_agent_list'))
        self.assertEqual(resp_coach.status_code, 200)
        self.assertContains(resp_coach, "🟢 Available")

        resp_coach_home = self.client.get(reverse('home'))
        self.assertContains(resp_coach_home, reverse('free_agent_list'))

    def test_assigned_referee_can_score_game_least_privilege(self):
        from leagues.models import GameOfficialAssignment
        ref = CustomUser.objects.create_user(
            username="official_dan", password="password123", role="player"
        )
        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now() + timedelta(days=1), location="Gym 1"
        )

        # Before assignment: ref cannot score this specific game
        self.assertFalse(ref.can_score_game(game))

        # Assign ref as Head Referee
        assignment = GameOfficialAssignment.objects.create(
            game=game, official=ref, role='head_ref', status='confirmed'
        )
        self.assertTrue(ref.can_score_game(game))

        # Regular player still cannot score
        self.assertFalse(self.player_user.can_score_game(game))


    def test_unsigned_user_home_dashboard(self):
        unsigned_user = CustomUser.objects.create_user(
            username="unverified@sportsball.local",
            email="unverified@sportsball.local",
            password="password123",
            role="player",
            waiver_signed=False,
            church=self.church
        )
        self.client.login(username="unverified@sportsball.local", password="password123")
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Liability Waiver &amp; Sportsmanship Covenant Required")
        self.assertContains(resp, "Sign Waiver Now")


    def test_home_dashboard_schedule_scoping_and_announcement_badge(self):
        # 1. Unassigned free agent views dashboard: No upcoming schedule, no redundant announcements card
        eli = CustomUser.objects.create_user(
            username="eli_walker", password="password123", role="player", is_free_agent=True
        )
        self.client.login(username="eli_walker", password="password123")
        resp_eli = self.client.get(reverse('home'))
        self.assertEqual(resp_eli.status_code, 200)
        self.assertNotContains(resp_eli, 'id="seeAllScheduleBtn"')
        self.assertNotContains(resp_eli, 'id="tabViewUpcoming"')

        # 2. Announcement created -> Sidebar displays alert badge
        Announcement.objects.create(
            title="Spring Registration Closes Friday",
            content="Please get your team dues in.",
            author=self.admin_user,
        )
        resp_badge = self.client.get(reverse('home'))
        self.assertContains(resp_badge, 'title="1 new announcement"')

        # 3. Rostered player views dashboard: Sees upcoming schedule with 'See All ->' and 'Recent Scores' tab
        self.team1.players.add(self.player_user)
        Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now() + timedelta(days=4), location="Diamond 1"
        )
        self.client.login(username="player_user", password="password123")
        resp_rostered = self.client.get(reverse('home'))
        self.assertEqual(resp_rostered.status_code, 200)
        self.assertContains(resp_rostered, 'id="seeAllScheduleBtn"')
        self.assertContains(resp_rostered, 'See All &rarr;')
        self.assertContains(resp_rostered, 'id="btnTabResults"')

    def test_dugout_active_scorer_lock_and_takeover(self):
        # Setup: Coach 1 (team1 captain) and Coach 2 (team2 captain)
        coach2 = CustomUser.objects.create_user(
            username="coach2_user", password="password123", role="coach", church=self.church
        )
        self.team2.captain = coach2
        self.team2.save()

        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Diamond 1", status='scheduled'
        )

        # 1. Coach 1 opens console -> acquires lock
        self.client.login(username="coach_user", password="password123")
        resp = self.client.get(reverse('dugout_console', args=[game.id]))
        self.assertEqual(resp.status_code, 200)
        game.refresh_from_db()
        self.assertEqual(game.active_scorer, self.coach_user)

        # 2. Coach 2 attempts an action -> HTTP 423 Locked
        self.client.login(username="coach2_user", password="password123")
        action_resp = self.client.post(
            reverse('dugout_action', args=[game.id]),
            data=json.dumps({'action': 'run_plus', 'team': 'team2'}),
            content_type='application/json'
        )
        self.assertEqual(action_resp.status_code, 423)
        self.assertTrue(action_resp.json().get('locked'))
        self.assertIn("currently active", action_resp.json().get('error'))

        # 3. Coach 2 takes over scoring
        takeover_resp = self.client.post(
            reverse('take_over_dugout_scoring', args=[game.id]),
            content_type='application/json'
        )
        self.assertEqual(takeover_resp.status_code, 200)
        game.refresh_from_db()
        self.assertEqual(game.active_scorer, coach2)

        # 4. Now Coach 2 can successfully score
        action_resp2 = self.client.post(
            reverse('dugout_action', args=[game.id]),
            data=json.dumps({'action': 'run_plus', 'team': 'team2', 'points': 1}),
            content_type='application/json'
        )
        self.assertEqual(action_resp2.status_code, 200)
        game.refresh_from_db()
        self.assertEqual(game.team2_score, 1)


    def test_official_referee_score_submission_bypasses_confirmation(self):
        # Certified referee assigned in Officials Hub
        referee = CustomUser.objects.create_user(
            username="referee_bob", password="password123", role="referee", church=self.church
        )
        self.season.officials_pool.add(referee)

        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Court 1", status='scheduled'
        )
        from leagues.models import GameOfficialAssignment
        GameOfficialAssignment.objects.create(
            game=game, official=referee, role='head_ref', status='confirmed'
        )

        # Referee submits score
        self.client.login(username="referee_bob", password="password123")
        post_data = {
            'team1_score': 55,
            'team2_score': 48,
            'status': 'completed',
            'notes': 'Clean game officiated by Bob.'
        }
        resp = self.client.post(reverse('record_game_score', args=[game.id]), post_data)
        self.assertEqual(resp.status_code, 302)

        game.refresh_from_db()
        # Authoritative: immediately completed and confirmed
        self.assertEqual(game.status, 'completed')
        self.assertTrue(game.score_confirmed)
        self.assertEqual(game.score_submitted_by, referee)

        # Standings immediately count the win
        standings = self.season.get_standings()
        eagles_standing = next(s for s in standings if s['team'] == self.team1)
        self.assertEqual(eagles_standing['wins'], 1)

        # Coach cannot overwrite referee score
        self.client.login(username="coach_user", password="password123")
        overwrite_resp = self.client.post(reverse('record_game_score', args=[game.id]), {
            'team1_score': 60,
            'team2_score': 48,
            'status': 'completed'
        })
        self.assertEqual(overwrite_resp.status_code, 302)
        game.refresh_from_db()
        self.assertEqual(game.team1_score, 55)  # Unchanged!


    def test_coach_score_submission_pending_confirmation_and_opponent_confirm(self):
        coach2 = CustomUser.objects.create_user(
            username="coach2_user", password="password123", role="coach", church=self.church
        )
        self.team2.captain = coach2
        self.team2.save()

        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Field A", status='scheduled'
        )

        # Coach 1 reports score
        self.client.login(username="coach_user", password="password123")
        resp = self.client.post(reverse('record_game_score', args=[game.id]), {
            'team1_score': 7,
            'team2_score': 4,
            'status': 'completed'
        })
        self.assertEqual(resp.status_code, 302)

        game.refresh_from_db()
        # Transitions to pending_confirmation, score_confirmed is False
        self.assertEqual(game.status, 'pending_confirmation')
        self.assertFalse(game.score_confirmed)
        self.assertEqual(game.score_submitted_by, self.coach_user)

        # Standings do NOT count unconfirmed score
        standings = self.season.get_standings()
        eagles_standing = next(s for s in standings if s['team'] == self.team1)
        self.assertEqual(eagles_standing['wins'], 0)

        # Coach 1 cannot confirm own score
        self_confirm = self.client.post(reverse('confirm_game_score', args=[game.id]))
        self.assertEqual(self_confirm.status_code, 302)
        game.refresh_from_db()
        self.assertFalse(game.score_confirmed)

        # Opposing Coach 2 views dashboard: sees pending score card
        self.client.login(username="coach2_user", password="password123")
        home_resp = self.client.get(reverse('home'))
        self.assertContains(home_resp, "Scores Awaiting Your Confirmation")
        self.assertContains(home_resp, "✓ Confirm Score")

        # Coach 2 1-taps confirmation
        confirm_resp = self.client.post(reverse('confirm_game_score', args=[game.id]))
        self.assertEqual(confirm_resp.status_code, 302)

        game.refresh_from_db()
        self.assertEqual(game.status, 'completed')
        self.assertTrue(game.score_confirmed)
        self.assertEqual(game.score_confirmed_by, coach2)

        # Standings now count the verified result
        standings_after = self.season.get_standings()
        eagles_after = next(s for s in standings_after if s['team'] == self.team1)
        self.assertEqual(eagles_after['wins'], 1)


    def test_coach_score_dispute_and_commissioner_resolution(self):
        coach2 = CustomUser.objects.create_user(
            username="coach2_user", password="password123", role="coach", church=self.church
        )
        self.team2.captain = coach2
        self.team2.save()

        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Field A", status='scheduled'
        )

        # Coach 1 submits score 12 - 3
        self.client.login(username="coach_user", password="password123")
        self.client.post(reverse('record_game_score', args=[game.id]), {
            'team1_score': 12,
            'team2_score': 3,
            'status': 'completed'
        })
        game.refresh_from_db()
        self.assertEqual(game.status, 'pending_confirmation')

        # Coach 2 disputes the score
        self.client.login(username="coach2_user", password="password123")
        disp_resp = self.client.post(reverse('dispute_game_score', args=[game.id]), {
            'dispute_notes': "Runs in 6th inning were not counted in opposing book. Correct score is 9-7.",
            'team1_score': 9,
            'team2_score': 7
        })
        self.assertEqual(disp_resp.status_code, 302)

        game.refresh_from_db()
        self.assertEqual(game.status, 'disputed')
        self.assertFalse(game.score_confirmed)
        self.assertIn("Runs in 6th inning were not counted", game.score_dispute_notes)

        # Commissioner command center shows disputed scores count
        self.client.login(username="admin_user", password="password123")
        commish_home = self.client.get(reverse('home'))
        self.assertContains(commish_home, "Disputed Scores")

        # Coach 2 cannot resolve the dispute (commissioner only)
        self.client.login(username="coach2_user", password="password123")
        unauth_resolve = self.client.post(reverse('resolve_score_dispute', args=[game.id]), {
            'team1_score': 9, 'team2_score': 7, 'resolution_notes': "Coach self resolution"
        })
        self.assertEqual(unauth_resolve.status_code, 302)
        game.refresh_from_db()
        self.assertEqual(game.status, 'disputed')

        # Commissioner resolves the dispute
        self.client.login(username="admin_user", password="password123")
        resolve_resp = self.client.post(reverse('resolve_score_dispute', args=[game.id]), {
            'team1_score': 10,
            'team2_score': 7,
            'resolution_notes': "Verified both scorebooks; 1 run ruled unearned in 6th."
        })
        self.assertEqual(resolve_resp.status_code, 302)

        game.refresh_from_db()
        self.assertEqual(game.status, 'completed')
        self.assertTrue(game.score_confirmed)
        self.assertEqual(game.team1_score, 10)
        self.assertEqual(game.team2_score, 7)
        self.assertEqual(game.score_confirmed_by, self.admin_user)
        self.assertIn("RESOLVED by", game.score_dispute_notes)


    def test_least_privilege_score_confirmation(self):
        unauth = CustomUser.objects.create_user(
            username="unauth_fan", password="password123", role="player"
        )
        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Field A", status='pending_confirmation',
            team1_score=5, team2_score=2, score_submitted_by=self.coach_user
        )

        self.client.login(username="unauth_fan", password="password123")
        # Unaffiliated player cannot confirm or dispute
        c_resp = self.client.post(reverse('confirm_game_score', args=[game.id]))
        self.assertEqual(c_resp.status_code, 302)
        game.refresh_from_db()
        self.assertFalse(game.score_confirmed)

        d_resp = self.client.post(reverse('dispute_game_score', args=[game.id]), {'dispute_notes': 'Spam'})
        self.assertEqual(d_resp.status_code, 302)
        game.refresh_from_db()
        self.assertEqual(game.status, 'pending_confirmation')


    def test_auto_finalize_stale_scores(self):
        # Game pending confirmation with score submitted 50 hours ago
        stale_game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now() - timedelta(days=3), location="Field A",
            status='pending_confirmation', team1_score=6, team2_score=4,
            score_submitted_by=self.coach_user,
            score_submitted_at=timezone.now() - timedelta(hours=50)
        )
        self.assertFalse(stale_game.score_confirmed)

        finalized_count = Game.auto_finalize_stale_pending_games(hours=48)
        self.assertGreaterEqual(finalized_count, 1)

        stale_game.refresh_from_db()
        self.assertEqual(stale_game.status, 'completed')
        self.assertTrue(stale_game.score_confirmed)
        self.assertIn("auto-confirmed", stale_game.score_audit_log[-1]['details'].lower())


    def test_bulk_confirm_pending_scores(self):
        g1 = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Field A", status='pending_confirmation',
            team1_score=5, team2_score=2, score_submitted_by=self.coach_user
        )
        g2 = Game.objects.create(
            season=self.season, team1=self.team2, team2=self.team1,
            date=timezone.now(), location="Field B", status='pending_confirmation',
            team1_score=11, team2_score=8, score_submitted_by=self.coach_user
        )

        self.client.login(username="admin_user", password="password123")
        resp = self.client.post(reverse('bulk_confirm_pending_scores'))
        self.assertEqual(resp.status_code, 302)

        g1.refresh_from_db()
        g2.refresh_from_db()
        self.assertEqual(g1.status, 'completed')
        self.assertTrue(g1.score_confirmed)
        self.assertEqual(g2.status, 'completed')
        self.assertTrue(g2.score_confirmed)


    def test_dugout_batch_sync_rejects_completed_game(self):
        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Field A", status='completed',
            team1_score=8, team2_score=5, score_confirmed=True
        )

        self.client.login(username="coach_user", password="password123")
        sync_payload = {
            'actions': [{'action': 'run_plus', 'team': 'team1', 'points': 5}]
        }
        resp = self.client.post(
            reverse('dugout_batch_sync', args=[game.id]),
            data=json.dumps(sync_payload),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json().get('status'), 'already_finalized')

        game.refresh_from_db()
        self.assertEqual(game.team1_score, 8)  # Score preserved!


    def test_forfeit_recording(self):
        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Field A", status='scheduled'
        )

        self.client.login(username="coach_user", password="password123")
        resp = self.client.post(reverse('record_game_forfeit', args=[game.id]), {
            'forfeiting_team_id': self.team1.id
        })
        self.assertEqual(resp.status_code, 302)

        game.refresh_from_db()
        self.assertEqual(game.status, 'completed')
        self.assertTrue(game.score_confirmed)
        self.assertEqual(game.winner, self.team2)
        self.assertEqual(game.team1_score, 0)
        self.assertGreater(game.team2_score, 0)
        self.assertIn("Forfeit recorded", game.score_audit_log[-1]['details'])


    def test_field_double_booking_validation(self):
        from leagues.forms import GameForm
        game_time = timezone.now() + timedelta(days=5)
        Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=game_time, location="Heritage Field 1", status='scheduled'
        )

        # Attempt to schedule another game 30 minutes later at same field
        local_clash_time = timezone.localtime(game_time) + timedelta(minutes=30)
        clashing_form = GameForm(data={
            'team1': self.team1.id,
            'team2': self.team2.id,
            'date': local_clash_time.strftime('%Y-%m-%dT%H:%M'),
            'location': 'Heritage Field 1',
            'game_type': 'regular',
            'status': 'scheduled',
            'week_number': 2,
        }, season=self.season)

        self.assertFalse(clashing_form.is_valid())
        self.assertIn("Venue Conflict", str(clashing_form.errors))


    def test_officials_payment_toggle(self):
        ref = CustomUser.objects.create_user(
            username="ref_tom", password="password123", role="referee"
        )
        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Field A", status='scheduled'
        )
        from leagues.models import GameOfficialAssignment
        assignment = GameOfficialAssignment.objects.create(
            game=game, official=ref, role='head_ref', pay_amount=35.00, pay_status='unpaid'
        )

        self.client.login(username="admin_user", password="password123")
        # 1. Mark paid
        resp1 = self.client.post(reverse('toggle_official_payment', args=[assignment.id]))
        self.assertEqual(resp1.status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.pay_status, 'paid')
        self.assertIsNotNone(assignment.paid_at)

        # 2. Mark unpaid
        resp2 = self.client.post(reverse('toggle_official_payment', args=[assignment.id]))
        self.assertEqual(resp2.status_code, 302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.pay_status, 'unpaid')
        self.assertIsNone(assignment.paid_at)


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


    def test_reschedule_rainouts(self):
        rainout_game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Heritage Park", status='rainout'
        )

        self.client.login(username="admin_user", password="password123")
        makeup_date = (timezone.now() + timedelta(days=14)).strftime('%Y-%m-%d')
        resp = self.client.post(reverse('reschedule_rainouts', args=[self.season.id]), {
            'selected_games': [rainout_game.id],
            'target_date': makeup_date,
            'target_time': '10:00',
            'interval_minutes': 60
        })
        self.assertEqual(resp.status_code, 302)

        rainout_game.refresh_from_db()
        self.assertEqual(rainout_game.status, 'scheduled')
        self.assertEqual(rainout_game.date.strftime('%Y-%m-%d'), makeup_date)
        self.assertIn("Rescheduled makeup", rainout_game.notes)


    def test_master_venues_pool(self):
        self.client.login(username="admin_user", password="password123")
        # Add venue to pool
        resp = self.client.post(reverse('add_league_venue', args=[self.league.id]), {
            'name': 'Heritage Diamond #3',
            'address': '100 Main St',
            'notes': 'Dugout gate code 1234'
        })
        self.assertEqual(resp.status_code, 302)
        venue = LeagueVenue.objects.get(league=self.league, name='Heritage Diamond #3')
        self.assertTrue(venue.is_active)

        # Toggle active
        resp = self.client.post(reverse('toggle_league_venue', args=[self.league.id, venue.id]))
        self.assertEqual(resp.status_code, 302)
        venue.refresh_from_db()
        self.assertFalse(venue.is_active)

        # Delete venue
        resp = self.client.post(reverse('delete_league_venue', args=[self.league.id, venue.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(LeagueVenue.objects.filter(id=venue.id).exists())

    def test_master_officials_pool(self):
        ref_user = CustomUser.objects.create_user(username='ref_master_test', password='password123', role='referee')
        self.client.login(username="admin_user", password="password123")
        # Add official to master pool
        resp = self.client.post(reverse('add_league_official', args=[self.league.id]), {
            'user_id': ref_user.id
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn(ref_user, self.league.master_officials_pool.all())

        # When creating a new season, verify auto-inheritance
        resp = self.client.post(reverse('create_season', args=[self.league.id]), {
            'name': 'Spring 2027 Inherited Officials',
            'start_date': '2027-04-01',
            'end_date': '2027-06-30',
            'registration_fee': 50.00,
            'max_roster_size': 20,
            'registration_open': True,
            'current': True
        })
        self.assertEqual(resp.status_code, 302)
        new_season = Season.objects.get(league=self.league, name='Spring 2027 Inherited Officials')
        self.assertIn(ref_user, new_season.officials_pool.all())

        # Remove official from master pool
        resp = self.client.post(reverse('remove_league_official', args=[self.league.id, ref_user.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn(ref_user, self.league.master_officials_pool.all())

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

    def test_disciplinary_game_count_suspension_and_auto_reinstatement(self):
        """Verifies game-count suspensions lock players from lineups and auto-reinstate as games complete."""
        player = self.player_user
        player.waiver_signed = True
        player.save(update_fields=['waiver_signed'])
        # Issue 2-game suspension
        record = PlayerDisciplinaryRecord.objects.create(
            player=player,
            league=self.league,
            team=self.team1,
            penalty_type='game_count',
            status='active',
            games_suspended_total=2,
            reason="Unsportsmanlike conduct technical foul",
            issued_by=self.admin_user
        )

        # Check player eligibility
        eligible, reason = player.is_eligible_to_play(self.league)
        self.assertFalse(eligible)
        self.assertIn("Suspended (2 game(s) remaining)", reason)

        # Coach attempts to mark player present in lineup builder -> forced False
        self.client.login(username="coach_user", password="password123")
        self.team1.players.add(player)
        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Field A", status='scheduled'
        )
        game.ensure_lineups_initialized()
        entry = game.lineup_entries.get(player=player)

        resp = self.client.post(reverse('game_lineup_builder', args=[game.id, self.team1.id]), {
            'action': 'save_lineup',
            f'order_{entry.id}': '1',
            f'position_{entry.id}': 'SS',
            f'present_{entry.id}': '1'  # Attempting to check present
        })
        self.assertEqual(resp.status_code, 302)
        entry.refresh_from_db()
        self.assertFalse(entry.is_present)  # Hard locked to False!

        # First game completes -> 1 game served
        game.status = 'completed'
        game.team1_score = 5
        game.team2_score = 3
        game.save()

        record.refresh_from_db()
        self.assertEqual(record.games_served, 1)
        self.assertEqual(record.status, 'active')
        eligible, reason = player.is_eligible_to_play(self.league)
        self.assertFalse(eligible)
        self.assertIn("Suspended (1 game(s) remaining)", reason)

        # Second game completes -> 2 games served, auto-reinstated!
        game2 = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now() + timedelta(days=7), location="Field A", status='scheduled'
        )
        game2.status = 'completed'
        game2.team1_score = 7
        game2.team2_score = 6
        game2.save()

        record.refresh_from_db()
        self.assertEqual(record.games_served, 2)
        self.assertEqual(record.status, 'served')
        self.assertIsNotNone(record.reinstated_at)

        # Eligibility is automatically restored!
        eligible, reason = player.is_eligible_to_play(self.league)
        self.assertTrue(eligible)
        self.assertEqual(reason, "Eligible")

    def test_permanent_expulsion_lockout(self):
        """Verifies permanent expulsion deactivates user login and enforces global ban."""
        player = self.player_user
        self.client.login(username="admin_user", password="password123")

        resp = self.client.post(reverse('manage_disciplinary_hub', args=[self.league.id]), {
            'action': 'create_disciplinary_record',
            'player_id': str(player.id),
            'penalty_type': 'permanent_expulsion',
            'reason': 'Egregious by-law violation and persistent misconduct',
            'dues_forfeited': '1'
        })
        self.assertEqual(resp.status_code, 302)

        player.refresh_from_db()
        self.assertTrue(player.is_expelled)
        self.assertFalse(player.is_active)  # Login locked out

        eligible, reason = player.is_eligible_to_play(self.league)
        self.assertFalse(eligible)
        self.assertIn("Permanently expelled", reason)

    def test_venue_status_update_and_game_relocation(self):
        """Verifies 1-click field relocation atomically updates scheduled games."""
        self.client.login(username="admin_user", password="password123")
        field1 = LeagueVenue.objects.create(league=self.league, name="Diamond #1", status="open")
        field2 = LeagueVenue.objects.create(league=self.league, name="Turf Complex #2", status="open")

        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Diamond #1", venue=field1, status='scheduled'
        )

        # Update field1 to closed due to standing water
        resp = self.client.post(reverse('update_venue_status', args=[field1.id]), {
            'status': 'closed',
            'status_note': 'Infield flooded from overnight storm'
        })
        self.assertEqual(resp.status_code, 302)
        field1.refresh_from_db()
        self.assertEqual(field1.status, 'closed')
        self.assertEqual(field1.status_note, 'Infield flooded from overnight storm')

        # Relocate games from field1 to field2
        resp = self.client.post(reverse('relocate_venue_games', args=[field1.id]), {
            'action_type': 'relocate',
            'new_venue_id': str(field2.id),
            'reason': 'Heavy standing water'
        })
        self.assertEqual(resp.status_code, 302)

        game.refresh_from_db()
        self.assertEqual(game.venue, field2)
        self.assertEqual(game.location, "Turf Complex #2")

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

    def test_sportsmanship_evaluations_and_configurable_thresholds(self):
        """Verifies fellowship scores, referee reviews, and committee renewal threshold updates."""
        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Field A", status='completed',
            team1_score=6, team2_score=4
        )

        # Umpire rates Team 1 exemplary (5★) and Team 2 contentious (2★)
        self.client.login(username="admin_user", password="password123")
        resp = self.client.post(reverse('submit_sportsmanship_rating', args=[game.id]), {
            'rated_team_id': str(self.team1.id),
            'score': '5',
            'respect_for_officials': '5',
            'bench_conduct': '5',
            'notes': 'Christlike attitude and tremendous fellowship'
        })
        self.assertEqual(resp.status_code, 302)

        resp = self.client.post(reverse('submit_sportsmanship_rating', args=[game.id]), {
            'rated_team_id': str(self.team2.id),
            'score': '2',
            'respect_for_officials': '2',
            'bench_conduct': '2',
            'notes': 'Repeated arguing with plate umpire'
        })
        self.assertEqual(resp.status_code, 302)

        # Default thresholds: Good >= 4.0, Review >= 3.0
        summary1 = self.team1.get_sportsmanship_summary()
        self.assertEqual(summary1['avg_score'], 5.0)
        self.assertEqual(summary1['status'], 'good')

        summary2 = self.team2.get_sportsmanship_summary()
        self.assertEqual(summary2['avg_score'], 2.0)
        self.assertEqual(summary2['status'], 'probation')

        # Committee updates standards: Good >= 4.5, Review >= 2.0
        resp = self.client.post(reverse('manage_sportsmanship_dashboard', args=[self.league.id]), {
            'update_thresholds': '1',
            'sportsmanship_good_threshold': '4.50',
            'sportsmanship_review_threshold': '2.00',
        })
        self.assertEqual(resp.status_code, 302)
        self.league.refresh_from_db()
        self.assertEqual(float(self.league.sportsmanship_good_threshold), 4.5)
        self.assertEqual(float(self.league.sportsmanship_review_threshold), 2.0)

        # With 2.0 review threshold, Team 2 shifts from probation to review required
        summary2_updated = self.team2.get_sportsmanship_summary()
        self.assertEqual(summary2_updated['status'], 'review')

    def test_minor_player_parental_waiver_safeguard(self):
        """Verifies minor eligibility checks and parental electronic consent execution."""
        from users.models import CustomUser
        parent = CustomUser.objects.create_user(
            username="parent_dan", email="parent@sportsball.local",
            password="sportsball123", first_name="Dan", last_name="Miller",
            role="player", waiver_signed=True
        )
        minor = CustomUser.objects.create_user(
            username="minor_timmy", email="timmy@sportsball.local",
            password="sportsball123", first_name="Timmy", last_name="Miller",
            role="player", birthdate=date.today() - timedelta(days=365 * 15),  # 15 years old
            parent_guardian=parent, waiver_signed=True  # Minor signed personal waiver
        )
        self.assertTrue(minor.is_minor)

        # 1. League does NOT allow minors
        self.league.allow_minors = False
        self.league.save()
        eligible, reason = minor.is_eligible_to_play(self.league)
        self.assertFalse(eligible)
        self.assertIn("Minors are not permitted", reason)

        # 2. League allows minors, but parent has not signed parental waiver yet
        self.league.allow_minors = True
        self.league.save()
        eligible, reason = minor.is_eligible_to_play(self.league)
        self.assertFalse(eligible)
        self.assertIn("Minor player waiver requires parent/guardian signature", reason)

        # 3. Parent logs in and executes parental electronic consent
        self.client.force_login(parent)
        resp = self.client.post(reverse('sign_parental_waiver', args=[minor.id]), {
            'parent_name': 'Dan Miller',
            'parent_phone': '(555) 789-0123',
            'parent_signature': 'Dan Miller (Father)'
        })
        self.assertEqual(resp.status_code, 302)

        minor.refresh_from_db()
        self.assertTrue(minor.parent_signed_waiver)
        self.assertIsNotNone(minor.parent_waiver_signed_at)

        # Minor is now fully eligible!
        eligible, reason = minor.is_eligible_to_play(self.league)
        self.assertTrue(eligible)
        self.assertEqual(reason, "Eligible")
