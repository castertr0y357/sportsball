from tests.e2e.base_e2e import BasePlaywrightTestCase
from core.models import SystemSetting, BackupRecord


class SystemAdminAndGFSE2ETest(BasePlaywrightTestCase):
    """Verifies System Diagnostics, Emergency Alert Banners, 503 Maintenance Mode, and GFS Backups."""

    def test_system_admin_diagnostics_and_banner(self):
        page = self.page
        self.login_as(page, self.admin_user)

        # 1. Open System Diagnostics Dashboard
        page.goto(f"{self.live_server_url}/system-admin/")
        page.wait_for_load_state("networkidle")

        self.assertIn("Platform Telemetry", page.content())
        self.assertIn("Database Storage", page.content())
        self.assertIn("Active Sessions", page.content())

        # 2. Update Emergency Alert Banner
        page.fill('#banner_message', 'Weather Alert: All Friday games postponed due to rain')
        page.check('input[name="banner_active"]')
        page.locator('form button:has-text("Save Banner")').click()
        page.wait_for_load_state("networkidle")

        # Verify emergency banner is rendered on home page
        page.goto(f"{self.live_server_url}/")
        page.wait_for_load_state("networkidle")

        self.assertIn("emergency-alert-banner", page.content())
        self.assertIn("Weather Alert: All Friday games postponed due to rain", page.content())

        # Clean up banner
        setting = SystemSetting.get_settings()
        setting.banner_active = False
        setting.save()

    def test_maintenance_mode_and_gfs_backup_creation(self):
        page = self.page
        # Auto-accept any browser confirm() prompts
        page.on("dialog", lambda dialog: dialog.accept())

        self.login_as(page, self.admin_user)

        # 1. Toggle Maintenance Mode ON
        page.goto(f"{self.live_server_url}/system-admin/")
        page.wait_for_load_state("networkidle")

        page.locator('form button:has-text("Enable Maintenance Mode")').click()
        page.wait_for_load_state("networkidle")

        setting = SystemSetting.get_settings()
        self.assertTrue(setting.maintenance_mode)

        # 2. Verify Anonymous Visitor gets 503 screen
        guest_context = self.browser.new_context()
        guest_page = guest_context.new_page()

        resp = guest_page.goto(f"{self.live_server_url}/")
        self.assertEqual(resp.status, 503)
        self.assertIn("Scheduled Upgrades Underway", guest_page.content())
        guest_context.close()

        # 3. Superuser brings site back live
        page.goto(f"{self.live_server_url}/system-admin/")
        page.locator('form button:has-text("Disable Maintenance Mode")').click()
        page.wait_for_load_state("networkidle")

        setting.refresh_from_db()
        self.assertFalse(setting.maintenance_mode)

        # 4. GFS Backups Console: Trigger Manual Snapshot
        page.goto(f"{self.live_server_url}/system-admin/backups/")
        page.wait_for_load_state("networkidle")

        self.assertIn("GFS Automated Backups", page.content())

        # Trigger manual backup
        page.locator('form button:has-text("Create Manual Snapshot Now")').click()
        page.wait_for_load_state("networkidle")

        self.assertIn("Manual backup created successfully", page.content())
        self.assertTrue(BackupRecord.objects.filter(status='SUCCESS').exists())
