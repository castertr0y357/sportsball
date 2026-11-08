"""
Adversarial and Chaos Break-Testing Suite:
- Softball Short-Handed 1-Out Differential Matrix (8 vs 8, 9 vs 9, 8 vs 9, 9 vs 10, 8 vs 10)
- Automatic Out Inning Flip (2 outs -> 3 outs retire side) and wrap-around
- Mid-Inning Injury / Ejection Rotation Wrap Without IndexError
- 3-Way Circular Standings Deadlock (Rock-Paper-Scissors Tiebreaker)
- IDOR Security Protection (Safety Roster and Audio Veto)
- Audio Replacement Cascade Deletion Safety
"""
from datetime import date, timedelta
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Church
from leagues.models import Game, League, Season, Team, GameLineupEntry
from leagues.services import scoring_engine
from users.models import AudioTrack, CustomUser


class TestChaosAndBreakScenarios(TestCase):
    def setUp(self):
        self.church = Church.objects.create(name="Grace Community Church", city="Columbia", state="SC")
        self.admin = CustomUser.objects.create_user(username="league_commish", password="pw", role="admin", church=self.church)
        self.coach1 = CustomUser.objects.create_user(username="coach_one", password="pw", role="coach", church=self.church)
        self.coach2 = CustomUser.objects.create_user(username="coach_two", password="pw", role="coach", church=self.church)

        self.league = League.objects.create(name="Church Softball League", sport="softball", admin=self.admin)
        self.season = Season.objects.create(
            league=self.league,
            name="Spring 2026",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=60),
            current=True
        )
        self.team1 = Team.objects.create(name="Grace Sluggers", league=self.league, season=self.season, church=self.church, captain=self.coach1)
        self.team2 = Team.objects.create(name="Calvary Crusaders", league=self.league, season=self.season, church=self.church, captain=self.coach2)

        # Create pool of players
        self.team1_players = [
            CustomUser.objects.create_user(username=f"t1_p{i}", password="pw", role="player", church=self.church)
            for i in range(1, 11)
        ]
        self.team2_players = [
            CustomUser.objects.create_user(username=f"t2_p{i}", password="pw", role="player", church=self.church)
            for i in range(1, 11)
        ]
        self.team1.players.set(self.team1_players)
        self.team2.players.set(self.team2_players)

        self.game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now(),
            location="Sanctuary Field 1",
            status='scheduled',
            game_type='regular'
        )

    def _setup_lineup(self, team, player_count):
        """Helper to create active lineup entries with exact player count."""
        GameLineupEntry.objects.filter(game=self.game, team=team).delete()
        players = self.team1_players if team == self.team1 else self.team2_players
        for i in range(player_count):
            GameLineupEntry.objects.create(
                game=self.game,
                team=team,
                player=players[i],
                batting_order=i + 1,
                is_present=True,
                is_automatic_out=False
            )

    def test_softball_shorthanded_one_out_matrix(self):
        """
        Verifies exact 1-out differential rule:
        - 8 vs 8 -> 0 outs
        - 9 vs 9 -> 0 outs
        - 10 vs 10 -> 0 outs
        - 8 vs 9 -> 8 takes 1 out at #9; 9 takes 0 outs
        - 9 vs 10 -> 9 takes 1 out at #10; 10 takes 0 outs
        - 8 vs 10 -> 8 takes 1 out at #9; 10 takes 0 outs
        - 10 vs 8 -> 8 takes 1 out at #9; 10 takes 0 outs
        """
        # Case 1: 8 vs 8 -> 0 outs
        self._setup_lineup(self.team1, 8)
        self._setup_lineup(self.team2, 8)
        res = self.game.sync_shorthanded_automatic_outs()
        self.assertFalse(res['team1_penalty'])
        self.assertFalse(res['team2_penalty'])
        self.assertEqual(self.game.lineup_entries.filter(is_automatic_out=True).count(), 0)

        # Case 2: 9 vs 9 -> 0 outs
        self._setup_lineup(self.team1, 9)
        self._setup_lineup(self.team2, 9)
        res = self.game.sync_shorthanded_automatic_outs()
        self.assertFalse(res['team1_penalty'])
        self.assertFalse(res['team2_penalty'])
        self.assertEqual(self.game.lineup_entries.filter(is_automatic_out=True).count(), 0)

        # Case 3: 10 vs 10 -> 0 outs
        self._setup_lineup(self.team1, 10)
        self._setup_lineup(self.team2, 10)
        res = self.game.sync_shorthanded_automatic_outs()
        self.assertFalse(res['team1_penalty'])
        self.assertFalse(res['team2_penalty'])
        self.assertEqual(self.game.lineup_entries.filter(is_automatic_out=True).count(), 0)

        # Case 4: 8 vs 9 -> Team 1 has 8, takes 1 out at Spot #9. Team 2 takes 0 outs.
        self._setup_lineup(self.team1, 8)
        self._setup_lineup(self.team2, 9)
        res = self.game.sync_shorthanded_automatic_outs()
        self.assertTrue(res['team1_penalty'])
        self.assertFalse(res['team2_penalty'])
        self.assertEqual(res['penalty_spot_team1'], 9)
        self.assertEqual(self.game.lineup_entries.filter(is_automatic_out=True).count(), 1)
        entry = self.game.lineup_entries.get(is_automatic_out=True)
        self.assertEqual(entry.team, self.team1)
        self.assertEqual(entry.batting_order, 9)

        # Case 5: 9 vs 10 -> Team 1 has 9, takes 1 out at Spot #10. Team 2 takes 0 outs.
        self._setup_lineup(self.team1, 9)
        self._setup_lineup(self.team2, 10)
        res = self.game.sync_shorthanded_automatic_outs()
        self.assertTrue(res['team1_penalty'])
        self.assertFalse(res['team2_penalty'])
        self.assertEqual(res['penalty_spot_team1'], 10)
        self.assertEqual(self.game.lineup_entries.filter(is_automatic_out=True).count(), 1)

        # Case 6: 8 vs 10 -> Team 1 has 8, takes EXACTLY 1 out at Spot #9 (not two outs!).
        self._setup_lineup(self.team1, 8)
        self._setup_lineup(self.team2, 10)
        res = self.game.sync_shorthanded_automatic_outs()
        self.assertTrue(res['team1_penalty'])
        self.assertFalse(res['team2_penalty'])
        self.assertEqual(res['penalty_spot_team1'], 9)
        self.assertEqual(self.game.lineup_entries.filter(is_automatic_out=True).count(), 1)

        # Case 7: 10 vs 8 (Reverse) -> Team 2 has 8, takes 1 out at Spot #9. Team 1 has 0 outs.
        self._setup_lineup(self.team1, 10)
        self._setup_lineup(self.team2, 8)
        res = self.game.sync_shorthanded_automatic_outs()
        self.assertFalse(res['team1_penalty'])
        self.assertTrue(res['team2_penalty'])
        self.assertEqual(res['penalty_spot_team2'], 9)
        self.assertEqual(self.game.lineup_entries.filter(is_automatic_out=True).count(), 1)
        entry = self.game.lineup_entries.get(is_automatic_out=True)
        self.assertEqual(entry.team, self.team2)
        self.assertEqual(entry.batting_order, 9)

    def test_softball_auto_out_gameplay_two_outs_retires_side(self):
        """When a short-handed team reaches their automatic out slot with 2 outs, it records 3rd out and flips inning."""
        # Team 1 has 8 players, Team 2 has 10
        self._setup_lineup(self.team1, 8)
        self._setup_lineup(self.team2, 10)
        self.game.sync_shorthanded_automatic_outs()

        # Set game in progress, bottom of 1st (Team 1 batting)
        self.game.status = 'in_progress'
        self.game.current_inning = 1
        self.game.inning_half = 'bot'  # Team 1 bats
        self.game.outs = 2
        self.game.team1_batter_index = 8  # Next is index 8 (which is Spot #9, the automatic out slot)
        self.game.save()

        # Advance to next batter
        next_batter = self.game.advance_to_next_batter()

        # Because it was 2 outs, the automatic out made 3 outs!
        # Side retired: switches to top of 2nd, outs reset to 0
        self.assertEqual(self.game.current_inning, 2)
        self.assertEqual(self.game.inning_half, 'top')
        self.assertEqual(self.game.outs, 0)
        self.assertIsNone(next_batter)
        self.assertIn("Auto-Out", self.game.play_by_play[0])

    def test_softball_auto_out_gameplay_zero_outs_advances_to_top_of_order(self):
        """When automatic out is assessed with < 2 outs, it increments outs and skips immediately to batter #1."""
        self._setup_lineup(self.team1, 8)
        self._setup_lineup(self.team2, 10)
        self.game.sync_shorthanded_automatic_outs()

        self.game.status = 'in_progress'
        self.game.current_inning = 1
        self.game.inning_half = 'bot'  # Team 1 bats
        self.game.outs = 0
        self.game.team1_batter_index = 8  # Spot #9 is automatic out
        self.game.save()

        next_batter = self.game.advance_to_next_batter()

        # 1 out recorded on board
        self.assertEqual(self.game.outs, 1)
        # Inning does NOT flip
        self.assertEqual(self.game.current_inning, 1)
        self.assertEqual(self.game.inning_half, 'bot')
        # Batter #1 is up at the plate!
        self.assertEqual(next_batter, self.team1_players[0])
        self.assertEqual(self.game.current_batter, self.team1_players[0])

    def test_lineup_mid_game_injury_ejection_shift_without_crash(self):
        """Ejecting or benching the last batter in rotation mid-game must wrap without an IndexError."""
        self._setup_lineup(self.team1, 10)
        self._setup_lineup(self.team2, 10)

        self.game.status = 'in_progress'
        self.game.inning_half = 'bot'  # Team 1
        self.game.team1_batter_index = 9  # Batter 10
        self.game.save()

        # Player 10 gets injured mid-game and is marked not present
        last_entry = self.game.lineup_entries.get(team=self.team1, batting_order=10)
        last_entry.is_present = False
        last_entry.save(update_fields=['is_present'])

        # Advancing to next batter must wrap to index 0 (Batter 1) cleanly without raising IndexError
        try:
            batter = self.game.advance_to_next_batter()
            self.assertEqual(batter, self.team1_players[0])
        except IndexError:
            self.fail("advance_to_next_batter raised IndexError when rotation size shrunk mid-game!")

    def test_three_way_circular_deadlock_standings_tiebreaker(self):
        """
        Tests 3-way circular tie (Team A beat B, B beat C, C beat A) with identical records.
        Verifies get_standings() resolves ranks deterministically via run differential without hanging.
        """
        team3 = Team.objects.create(name="Zion Thunder", league=self.league, season=self.season, church=self.church, captain=self.coach1)

        # Game 1: Team 1 (Sluggers) beat Team 2 (Crusaders) 10 - 5
        Game.objects.create(season=self.season, team1=self.team1, team2=self.team2, date=timezone.now(), status='completed', team1_score=10, team2_score=5, score_confirmed=True)
        # Game 2: Team 2 (Crusaders) beat Team 3 (Thunder) 8 - 4
        Game.objects.create(season=self.season, team1=self.team2, team2=team3, date=timezone.now(), status='completed', team1_score=8, team2_score=4, score_confirmed=True)
        # Game 3: Team 3 (Thunder) beat Team 1 (Sluggers) 6 - 2
        Game.objects.create(season=self.season, team1=team3, team2=self.team1, date=timezone.now(), status='completed', team1_score=6, team2_score=2, score_confirmed=True)

        standings = self.season.get_standings()
        self.assertEqual(len(standings), 3)

        # All 3 teams are 1-1
        for row in standings:
            self.assertEqual(row['wins'], 1)
            self.assertEqual(row['losses'], 1)

        # Verified rank order based on run differential:
        # Team 1: GF 12, GA 11 -> Diff +1
        # Team 2: GF 13, GA 14 -> Diff -1
        # Team 3: GF 10, GA 10 -> Diff 0
        diffs = [row['point_diff'] for row in standings]
        self.assertEqual(diffs, sorted(diffs, reverse=True))

    def test_security_safety_roster_idor_protection(self):
        """Unauthorized player cannot scrape private emergency contacts of a rival team."""
        rival_player = self.team2_players[0]
        self.client.force_login(rival_player)

        # Rival tries to view Team 1's safety roster
        url = reverse('team_safety_roster', kwargs={'team_id': self.team1.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse('team_detail', kwargs={'team_id': self.team1.id}))

    def test_security_audio_veto_idor_protection(self):
        """Unauthorized player cannot veto another team's audio track."""
        sample_audio = SimpleUploadedFile("track.mp3", b"content", content_type="audio/mpeg")
        team2_anthem = AudioTrack.objects.create(
            team=self.team2,
            track_type='team_intro',
            title="Calvary Battle Cry",
            audio_file=sample_audio,
            status='approved'
        )

        # Team 1 player tries to veto Team 2's anthem
        t1_player = self.team1_players[0]
        self.client.force_login(t1_player)

        url = reverse('audio_veto', kwargs={'track_id': team2_anthem.id})
        resp = self.client.post(url, {'veto_reason': "We don't like their music."})
        self.assertEqual(resp.status_code, 302)

        team2_anthem.refresh_from_db()
        self.assertFalse(team2_anthem.is_vetoed)
        self.assertEqual(team2_anthem.status, 'approved')

    def test_audio_replacement_deletion_cascade_safety(self):
        """When an assigned replacement track is deleted, the vetoed track remains safe without crashing."""
        sample_audio = SimpleUploadedFile("track.mp3", b"content", content_type="audio/mpeg")
        good_track = AudioTrack.objects.create(
            title="Clean Worship Song",
            audio_file=sample_audio,
            status='approved'
        )
        bad_track = AudioTrack.objects.create(
            user=self.team1_players[0],
            title="Vetoed Track",
            audio_file=sample_audio,
            status='vetoed',
            replacement_track=good_track
        )

        # Delete the good replacement track
        good_track.delete()

        # Bad track replacement becomes None via SET_NULL
        bad_track.refresh_from_db()
        self.assertIsNone(bad_track.replacement_track)

        # Playback safely falls back to empty string without raising an exception
        url, start, dur = bad_track.get_effective_playback()
        self.assertEqual(url, "")
        self.assertEqual(start, 0.0)
