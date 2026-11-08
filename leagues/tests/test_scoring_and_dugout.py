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



class TestScoringAndDugoutCase(BaseLeagueTestCase):

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



    def test_scorekeeper_undo_stack(self):
        """Verifies the 10-state undo stack correctly rolls back plays, runners, and scores."""
        self.client.force_login(self.admin_user)
        g = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now(),
            location="Field A",
            status="in_progress",
            current_inning=1,
            inning_half="top",
            outs=0,
            team1_score=0,
            team2_score=0
        )
        g.ensure_lineups_initialized()
        url = reverse('dugout_action', args=[g.id])

        # 1. Action: Single (Hit + runner on 1B)
        resp = self.client.post(url, json.dumps({'action': 'single'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['runner_on_first'])
        self.assertTrue(data['can_undo'])

        # 2. Action: Home run (Score +2, runners cleared)
        resp = self.client.post(url, json.dumps({'action': 'homerun'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['team2_score'], 2)
        self.assertFalse(data['runner_on_first'])

        # 3. Action: Out (+1 out)
        resp = self.client.post(url, json.dumps({'action': 'out'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['outs'], 1)

        # 4. UNDO 1: Reverts Out (outs back to 0, score remains 2)
        resp = self.client.post(url, json.dumps({'action': 'undo'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['outs'], 0)
        self.assertEqual(data['team2_score'], 2)

        # 5. UNDO 2: Reverts Home Run (score back to 0, runner on 1B restored!)
        resp = self.client.post(url, json.dumps({'action': 'undo'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['team2_score'], 0)
        self.assertTrue(data['runner_on_first'])

        # 6. UNDO 3: Reverts Single (runner on 1B cleared, back to clean inning!)
        resp = self.client.post(url, json.dumps({'action': 'undo'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['runner_on_first'])
        self.assertEqual(data['team2_hits'], 0)


    def test_diamond_expanded_actions_and_runner_advancement(self):
        """Verifies 2B, 3B, Sac Fly, Fielder's Choice, Errors, Base Runner movement, and Multi-Out plays."""
        self.client.force_login(self.admin_user)
        self.league.sport = 'softball'
        self.league.save()
        g = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now(),
            location="Diamond #1",
            status="in_progress",
            current_inning=1,
            inning_half="top"
        )
        g.ensure_lineups_initialized()
        url = reverse('dugout_action', args=[g.id])

        # 1. Double (2B): Batter on 2B
        resp = self.client.post(url, json.dumps({'action': 'double'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['runner_on_second'])
        self.assertEqual(data['team2_hits'], 1)

        # 2. Advance Runner: Move runner from 2B to 3B
        resp = self.client.post(url, json.dumps({'action': 'advance_runner', 'from_base': '2B', 'to_base': '3B'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['runner_on_second'])
        self.assertTrue(data['runner_on_third'])

        # 3. Sacrifice Fly: Out recorded, runner from 3B scores (+1 run)
        resp = self.client.post(url, json.dumps({'action': 'sacrifice_fly'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['outs'], 1)
        self.assertEqual(data['team2_score'], 1)
        self.assertFalse(data['runner_on_third'])

        # 4. Reached on Error (E): Safe at 1B, but NO official hit credited!
        resp = self.client.post(url, json.dumps({'action': 'reached_on_error'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['runner_on_first'])
        self.assertEqual(data['team2_hits'], 1)  # Hits did NOT increase!

        # 5. Fielder's Choice (FC): Lead runner out, batter safe at 1B
        resp = self.client.post(url, json.dumps({'action': 'fielders_choice'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['outs'], 2)
        self.assertTrue(data['runner_on_first'])

        # 6. Strikeout: Looking (ꓘ) records 3rd out -> auto switches half inning!
        resp = self.client.post(url, json.dumps({'action': 'strikeout', 'style': 'looking'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['outs'], 0)  # Reset for bottom
        self.assertEqual(data['inning_half'], 'bottom')


    def test_inning_run_limit_and_mercy_rules(self):
        """Verifies 5-run max inning enforcement and tiered mercy rule triggering."""
        self.client.force_login(self.admin_user)
        self.league.sport = 'softball'
        self.league.inning_run_limit = 5
        self.league.mercy_rule_tier1_runs = 20
        self.league.mercy_rule_tier1_inning = 3
        self.league.save()

        g = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now(),
            location="Diamond #2",
            status="in_progress",
            current_inning=1,
            inning_half="top",
            current_half_runs=0
        )
        g.ensure_lineups_initialized()
        url = reverse('dugout_action', args=[g.id])

        # Score 4 runs
        self.client.post(url, json.dumps({'action': 'run_plus', 'team': 'team2', 'points': 4}), content_type='application/json')
        g.refresh_from_db()
        self.assertEqual(g.current_half_runs, 4)
        self.assertEqual(g.inning_half, 'top')

        # Score 1 more run -> 5-run limit reached! Auto-retires side and switches to bottom!
        resp = self.client.post(url, json.dumps({'action': 'run_plus', 'team': 'team2', 'points': 1}), content_type='application/json')
        data = resp.json()
        self.assertEqual(data['inning_half'], 'bottom')
        self.assertEqual(data['current_half_runs'], 0)

        # Test Mercy Rule: Lead of 21 runs after 3 innings
        g.current_inning = 3
        g.team2_score = 25
        g.team1_score = 4
        g.save()
        mercy = g.check_mercy_rule()
        self.assertTrue(mercy['triggered'])
        self.assertEqual(mercy['diff'], 21)

        # Playoff game: when enforce_mercy_rule_in_playoffs is False, mercy is bypassed
        g.game_type = 'playoff_final'
        g.save()
        self.league.enforce_mercy_rule_in_playoffs = False
        self.league.save()
        g.season.league = self.league
        mercy_playoffs = g.check_mercy_rule()
        self.assertFalse(mercy_playoffs['triggered'])


    def test_count_tracker_and_courtesy_foul(self):
        """Verifies 1-1 count start, ball/strike progression, and courtesy foul rule."""
        self.client.force_login(self.admin_user)
        self.league.sport = 'softball'
        self.league.softball_count_1_1_start = True
        self.league.allow_courtesy_foul = True
        self.league.save()

        g = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now(),
            location="Diamond #3",
            status="in_progress"
        )
        g.ensure_lineups_initialized()
        g.reset_batter_count()
        g.save()
        self.assertEqual(g.balls, 1)
        self.assertEqual(g.strikes, 1)
        url = reverse('dugout_action', args=[g.id])

        # 1. Foul ball with 1 strike -> strikes become 2
        self.client.post(url, json.dumps({'action': 'count_foul'}), content_type='application/json')
        g.refresh_from_db()
        self.assertEqual(g.strikes, 2)
        self.assertFalse(g.courtesy_foul_used)

        # 2. Foul ball with 2 strikes -> COURTESY FOUL USED (safe, still at bat)
        resp = self.client.post(url, json.dumps({'action': 'count_foul'}), content_type='application/json')
        data = resp.json()
        self.assertTrue(data['courtesy_foul_used'])
        self.assertEqual(data['outs'], 0)

        # 3. Subsequent foul ball with 2 strikes -> STRIKE 3 OUT!
        resp = self.client.post(url, json.dumps({'action': 'count_foul'}), content_type='application/json')
        data = resp.json()
        self.assertEqual(data['outs'], 1)


    def test_basketball_fouls_and_volleyball_sets(self):
        """Verifies Basketball team fouls bonus levels and Volleyball set progression."""
        self.client.force_login(self.admin_user)
        # Basketball
        self.league.sport = 'basketball'
        self.league.save()
        gb = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Gym Court 1", status="in_progress"
        )
        url_b = reverse('dugout_action', args=[gb.id])

        # 6 team fouls -> no bonus
        for _ in range(6):
            self.client.post(url_b, json.dumps({'action': 'team_foul', 'team': 'team1'}), content_type='application/json')
        gb.refresh_from_db()
        self.assertEqual(gb.team1_fouls, 6)

        # 7th team foul -> BONUS 1-and-1 active!
        resp = self.client.post(url_b, json.dumps({'action': 'team_foul', 'team': 'team1'}), content_type='application/json')
        data = resp.json()
        self.assertTrue(data['team1_bonus'])
        self.assertFalse(data['team1_double_bonus'])

        # 10th team foul -> DOUBLE BONUS active!
        for _ in range(3):
            resp = self.client.post(url_b, json.dumps({'action': 'team_foul', 'team': 'team1'}), content_type='application/json')
        data = resp.json()
        self.assertTrue(data['team1_double_bonus'])

        # Volleyball Set progression
        self.league.sport = 'volleyball'
        self.league.volleyball_set_cap = 27
        self.league.save()
        gv = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Volleyball Court", status="in_progress",
            team1_score=24, team2_score=20, current_set=1
        )
        url_v = reverse('dugout_action', args=[gv.id])
        resp_v = self.client.post(url_v, json.dumps({'action': 'volleyball_point', 'team': 'team1'}), content_type='application/json')
        data_v = resp_v.json()
        self.assertEqual(data_v['current_set'], 2)  # Set 1 won! Advanced to Set 2
        self.assertEqual(len(data_v['volleyball_sets']), 1)
        self.assertEqual(data_v['volleyball_sets'][0]['team1_score'], 25)


    def test_forfeit_and_rule_protest_logging(self):
        """Verifies 1-tap forfeit recording and rule protest audit trail snapshots."""
        self.client.force_login(self.admin_user)
        self.league.sport = 'softball'
        self.league.save()
        g = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Diamond #4", status="in_progress"
        )
        url = reverse('dugout_action', args=[g.id])

        # 1. Rule Protest
        resp_protest = self.client.post(url, json.dumps({
            'action': 'flag_dispute',
            'notes': 'Coach protested infield fly rule on runner leaving 1B'
        }), content_type='application/json')
        self.assertEqual(resp_protest.status_code, 200)
        g.refresh_from_db()
        self.assertTrue(any(e.get('action') == 'rule_protest' for e in g.score_audit_log))

        # 2. Forfeit: Award forfeit to Team 1
        resp_forfeit = self.client.post(url, json.dumps({
            'action': 'record_forfeit',
            'winner_id': self.team1.id,
            'notes': 'Opponent did not have enough players by 15 mins after start'
        }), content_type='application/json')
        self.assertEqual(resp_forfeit.status_code, 200)
        g.refresh_from_db()
        self.assertTrue(g.is_forfeit)
        self.assertEqual(g.forfeit_winner, self.team1)
        self.assertEqual(g.status, 'completed')
        self.assertEqual(g.team1_score, 7)  # Standard softball forfeit score
        self.assertEqual(g.team2_score, 0)

