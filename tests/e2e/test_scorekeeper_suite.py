from tests.e2e.base_e2e import BasePlaywrightTestCase


class ScorekeeperSuiteE2ETest(BasePlaywrightTestCase):
    """Verifies Dugout Console: Simple/Detailed Modes, Undo Stack, Count, Protests, and Bleacher Mode."""

    def test_scorekeeper_console_workflow(self):
        page = self.page

        # Overall Commissioner logs in and navigates to the live Dugout Console
        self.login_as(page, self.admin_user)
        dugout_url = f"{self.live_server_url}/leagues/games/{self.game.id}/console/"
        page.goto(dugout_url)
        page.wait_for_load_state("networkidle")

        # 1. Verify Scoreboard and Console Header
        content = page.content()
        self.assertIn("Grace Sluggers", content)
        self.assertIn("Calvary Crusaders", content)
        self.assertIn("Live Game Operator Console", content)

        # 2. Mode Switching: Simple Mode vs Detailed Mode
        # Switch to Simple Mode
        page.locator('#btn-mode-simple').click()
        page.wait_for_timeout(300)
        self.assertTrue(page.locator('#simple-mode-section').is_visible())
        self.assertFalse(page.locator('#detailed-mode-section').is_visible())

        # Switch back to Detailed Mode
        page.locator('#btn-mode-detailed').click()
        page.wait_for_timeout(300)
        self.assertTrue(page.locator('#detailed-mode-section').is_visible())
        self.assertFalse(page.locator('#simple-mode-section').is_visible())

        # 3. 1-Tap Scoring & Undo Stack
        # Click 1B Single
        page.locator('button.action-btn.btn-hit:has-text("1B Single")').click()
        page.wait_for_timeout(500)
        # Verify runner on 1B is occupied
        self.assertIn("occupied", page.locator('#base-1B').get_attribute("class") or "")

        # Click Home Run
        page.locator('button.action-btn.btn-hr:has-text("Home Run")').click()
        page.wait_for_timeout(500)
        # Away (Calvary) score should be 2
        self.assertEqual(page.locator('#team2-score').text_content().strip(), "2")
        self.assertNotIn("occupied", page.locator('#base-1B').get_attribute("class") or "")

        # Click Undo -> Score should revert to 0 and runner on 1B restored!
        page.locator('#btn-undo-top').click()
        page.wait_for_timeout(500)
        self.assertEqual(page.locator('#team2-score').text_content().strip(), "0")
        self.assertIn("occupied", page.locator('#base-1B').get_attribute("class") or "")

        # Click Undo again -> Runner on 1B cleared back to clean start
        page.locator('#btn-undo-top').click()
        page.wait_for_timeout(500)
        self.assertNotIn("occupied", page.locator('#base-1B').get_attribute("class") or "")

        # 4. Count Tracker (Plate Count)
        # Click + Ball
        page.locator('button:has-text("+ Ball")').click()
        page.wait_for_timeout(300)
        self.assertIn("filled-ball", page.locator('#ball-dot-1').get_attribute("class") or "")

        # Click + Strike
        page.locator('button:has-text("+ Strike")').click()
        page.wait_for_timeout(300)
        self.assertIn("filled-strike", page.locator('#strike-dot-1').get_attribute("class") or "")

        # Reset count
        page.locator('button:has-text("Reset Count")').click()
        page.wait_for_timeout(300)

        # 5. Rule Protest / Disputed Play Modal
        page.locator('button:has-text("⚖️ Protest")').click()
        page.wait_for_timeout(300)
        self.assertTrue(page.locator('#disputeModal').is_visible())

        page.fill('#disputeNotesInput', 'Disputed sliding contact rule at 2nd base')
        page.locator('#disputeModal button:has-text("Save Protest to Game Log")').click()
        page.wait_for_timeout(500)

        # Verify protest appears in Play-by-Play list
        self.assertIn("RULE PROTEST", page.locator('#play-by-play-list').text_content())
        self.assertIn("Disputed sliding contact rule", page.locator('#play-by-play-list').text_content())

        # 6. Bleacher Sunlight High-Contrast Mode Toggle
        page.locator('button:has-text("☀️ Sun Mode")').click()
        page.wait_for_timeout(200)
        # Body should have bleacher-mode class
        body_class = page.evaluate("() => document.body.className")
        self.assertIn("bleacher-mode", body_class)

        # Toggle back
        page.locator('button:has-text("☀️ Sun Mode")').click()
        page.wait_for_timeout(200)
        body_class_after = page.evaluate("() => document.body.className")
        self.assertNotIn("bleacher-mode", body_class_after)
