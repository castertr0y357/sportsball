from tests.e2e.base_e2e import BasePlaywrightTestCase
from leagues.models import Game


class ScoreDisputesE2ETest(BasePlaywrightTestCase):
    """Verifies Two-Party Score Confirmation, Dispute Flagging, and Commissioner Dispute Resolution."""

    def test_two_party_score_confirmation_and_dispute_resolution(self):
        page = self.page

        # Step 1: Coach Grace reports score (Grace Sluggers 8, Calvary Crusaders 5)
        self.login_as(page, self.coach_grace)
        score_url = f"{self.live_server_url}/leagues/games/{self.game.id}/score/"
        page.goto(score_url)
        page.wait_for_load_state("networkidle")

        page.fill('input[name="team1_score"]', '8')
        page.fill('input[name="team2_score"]', '5')
        page.select_option('select[name="status"]', 'completed')
        page.locator('form button:has-text("Save Score")').click()
        page.wait_for_load_state("networkidle")

        # Verify game is pending confirmation in database
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, 'pending_confirmation')
        self.assertEqual(self.game.team1_score, 8)
        self.assertEqual(self.game.team2_score, 5)
        self.assertFalse(self.game.score_confirmed)

        # Step 2: Coach David (Calvary) logs in and disputes the score on Game Detail
        self.login_as(page, self.coach_calvary)
        game_detail_url = f"{self.live_server_url}/leagues/games/{self.game.id}/"
        page.goto(game_detail_url)
        page.wait_for_load_state("networkidle")

        # Verify dispute prompt is visible to opposing coach
        self.assertIn("Pending Opponent Confirmation", page.content())
        self.assertIn("Disagree / Dispute Score", page.content())

        # Click dispute toggle button to reveal form
        page.locator('button:has-text("Disagree / Dispute Score")').click()

        # Submit dispute
        dispute_form = page.locator('#dispute-form-wrap')
        dispute_form.locator('input[name="team1_score"]').fill('6')
        dispute_form.locator('input[name="team2_score"]').fill('7')
        dispute_form.locator('textarea[name="dispute_notes"]').fill('Calvary won 7-6 in 7th inning')
        dispute_form.locator('button[type="submit"]').click()
        page.wait_for_load_state("networkidle")

        # Verify game is marked disputed in database
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, 'disputed')
        self.assertIn("Disputed Game Score Under Review", page.content())

        # Step 3: Overall Commissioner Paul resolves the dispute on Game Detail
        self.login_as(page, self.admin_user)
        page.goto(game_detail_url)
        page.wait_for_load_state("networkidle")

        self.assertIn("Commissioner Dispute Ruling", page.content())

        # Commissioner enters verified final score
        resolve_form = page.locator('form[action*="resolve"]')
        resolve_form.locator('input[name="team1_score"]').fill('8')
        resolve_form.locator('input[name="team2_score"]').fill('6')
        resolve_form.locator('textarea[name="resolution_notes"]').fill('Verified with field umpire book: 8-6 Sluggers final')
        resolve_form.locator('button[type="submit"]').click()
        page.wait_for_load_state("networkidle")

        # Verify game is completed with official final score
        self.game.refresh_from_db()
        self.assertEqual(self.game.status, 'completed')
        self.assertTrue(self.game.score_confirmed)
        self.assertEqual(self.game.team1_score, 8)
        self.assertEqual(self.game.team2_score, 6)
        self.assertEqual(self.game.score_confirmed_by, self.admin_user)

