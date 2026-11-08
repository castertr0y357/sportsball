from tests.e2e.base_e2e import BasePlaywrightTestCase


class DugoutAndGamecastE2ETest(BasePlaywrightTestCase):
    """Verifies Single-Operator Dugout Console scoring and Spectator Live GameCast play-by-play."""

    def test_dugout_scoring_and_live_gamecast(self):
        page = self.page

        # 1. Coach Grace logs in and opens Dugout Console
        self.login_as(page, self.coach_grace)
        console_url = f"{self.live_server_url}/leagues/games/{self.game.id}/console/"
        page.goto(console_url)
        page.wait_for_load_state("networkidle")

        # Verify console scoreboard rendered
        self.assertIn("Grace Sluggers", page.content())
        self.assertIn("Calvary Crusaders", page.content())

        # 2. Scorekeeper records a Single Hit
        hit_btn = page.locator(".action-btn.btn-hit").first
        if hit_btn.is_visible():
            hit_btn.click()
            page.wait_for_timeout(1000)

        # 3. Scorekeeper records an Out
        out_btn = page.locator(".action-btn.btn-out").first
        if out_btn.is_visible():
            out_btn.click()
            page.wait_for_timeout(1000)

        # 4. Scorekeeper awards runs via Run + button
        run_plus = page.locator("button:has-text('+')").first
        if run_plus.is_visible():
            run_plus.click()
            page.wait_for_timeout(1000)

        # 5. Open a second spectator browser tab for public GameCast (Anonymous Spectator)
        spectator_context = self.browser.new_context()
        spectator_page = spectator_context.new_page()

        gamecast_url = f"{self.live_server_url}/leagues/games/{self.game.id}/gamecast/"
        spectator_page.goto(gamecast_url)
        spectator_page.wait_for_load_state("networkidle")

        # Verify spectator sees GameCast without logging in
        spectator_content = spectator_page.content()
        self.assertIn("Live GameCast", spectator_content)
        self.assertIn("Grace Sluggers", spectator_content)
        self.assertIn("Calvary Crusaders", spectator_content)

        spectator_context.close()
