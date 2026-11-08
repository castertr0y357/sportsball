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



class TestDisciplineAndConductCase(BaseLeagueTestCase):

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

