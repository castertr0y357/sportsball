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

        resp_churches = self.client.get(reverse('church_list'))
        self.assertEqual(resp_churches.status_code, 200)
        self.assertContains(resp_churches, "First Baptist Fellowship")

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
