import json
from datetime import date, timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import Church, Announcement
from users.models import CustomUser
from leagues.models import League, Season, Team, SeasonRegistration, Game
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

        # 4. Impartial referee can also operate Dugout action
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
