from tests.e2e.base_e2e import BasePlaywrightTestCase, IPHONE_VIEWPORT
from users.models import CustomUser


class OnboardingAndWaiverE2ETest(BasePlaywrightTestCase):
    """Verifies guest mobile responsiveness, navigation, registration, and digital waiver signing."""

    def test_mobile_viewport_and_guest_dropdown(self):
        """Simulates an iPhone 14 mobile browser session to ensure no UI scrunching or overlap."""
        mobile_context = self.browser.new_context(viewport=IPHONE_VIEWPORT)
        page = mobile_context.new_page()

        page.goto(f"{self.live_server_url}/")
        page.wait_for_load_state("networkidle")

        # 1. Verify Topbar Brand and Elements
        brand_name = page.locator(".brand-name")
        self.assertTrue(brand_name.is_visible())
        self.assertEqual(brand_name.inner_text().strip(), "SportsBall")

        # 2. Verify hamburger toggle is accessible
        sidebar_toggle = page.locator("#sidebarToggle")
        self.assertTrue(sidebar_toggle.is_visible())

        # 3. Verify Guest Dropdown button exists with 'Sign In'
        account_btn = page.locator("#accountDropdownBtn")
        self.assertTrue(account_btn.is_visible())
        self.assertIn("Sign In", account_btn.inner_text())

        # 4. Click Guest Dropdown & Verify Links
        account_btn.click()
        dropdown_panel = page.locator("#accountDropdownMenu")
        self.assertTrue(dropdown_panel.is_visible())
        self.assertIn("Welcome to SportsBall", dropdown_panel.inner_text())
        self.assertIn("Sign In / Log In", dropdown_panel.inner_text())
        self.assertIn("Join / Register", dropdown_panel.inner_text())

        # 5. Open mobile navigation drawer
        sidebar_toggle.click()
        sidebar = page.locator("#appSidebar")
        self.assertTrue(sidebar.is_visible())

        mobile_context.close()

    def test_registration_and_digital_waiver_flow(self):
        """Verifies end-to-end user registration and dedicated waiver covenant execution."""
        page = self.page
        page.goto(f"{self.live_server_url}/users/register/")
        page.wait_for_load_state("networkidle")

        # 1. Register a fresh player
        page.fill('input[name="first_name"]', 'Michael')
        page.fill('input[name="last_name"]', 'Davis')
        page.fill('input[name="email"]', 'mdavis@testchurch.local')
        page.fill('input[name="password1"]', 'Str0ngP@ssw0rd!2026')
        page.fill('input[name="password2"]', 'Str0ngP@ssw0rd!2026')

        page.locator('form button[type="submit"]').click()
        page.wait_for_load_state("networkidle")

        # Verify account created
        new_user = CustomUser.objects.filter(email='mdavis@testchurch.local').first()
        self.assertIsNotNone(new_user)
        self.assertEqual(new_user.first_name, 'Michael')
        self.assertTrue(new_user.waiver_signed)

        # 2. Test dedicated waiver signing flow with an unsigned player
        self.assertFalse(self.player_unverified.waiver_signed)
        self.login_as(page, self.player_unverified)

        page.goto(f"{self.live_server_url}/users/profile/waiver/")
        page.wait_for_load_state("networkidle")

        self.assertIn("Liability Waiver", page.content())

        # Sign waiver with matching full name
        page.fill('input[name="signature"]', 'Tommy Test')
        page.check('input[name="agree"]')
        page.locator('form button:has-text("Sign Waiver Electronically")').click()
        page.wait_for_load_state("networkidle")

        # Verify unverified player is now verified in database
        self.player_unverified.refresh_from_db()
        self.assertTrue(self.player_unverified.waiver_signed)
        self.assertEqual(self.player_unverified.waiver_signature, 'Tommy Test')
