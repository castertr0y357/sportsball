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



class TestOfficialsAndDuesCase(BaseLeagueTestCase):

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

