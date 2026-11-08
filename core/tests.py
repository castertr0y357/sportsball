import os
import gzip
from datetime import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from users.models import CustomUser
from core.models import SystemSetting, BackupConfiguration, BackupRecord, Announcement, Church
from core.services.backup_service import (
    execute_backup,
    restore_backup,
    encrypt_payload,
    decrypt_payload,
    determine_gfs_tier,
    enforce_gfs_retention,
    get_storage_driver,
)


class SystemAdminAndGFSTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = CustomUser.objects.create_superuser(
            username='sysadmin',
            email='admin@sportsball.local',
            password='AdminPassword123!',
            first_name='Sys',
            last_name='Admin'
        )
        self.player_user = CustomUser.objects.create_user(
            username='player1',
            email='player1@sportsball.local',
            password='PlayerPassword123!',
            first_name='Test',
            last_name='Player',
            role='player'
        )
        self.league_admin = CustomUser.objects.create_user(
            username='commish1',
            email='commish1@sportsball.local',
            password='CommishPassword123!',
            first_name='League',
            last_name='Commish',
            role='league_admin'
        )

        # Configure backup settings for tests in a temporary test directory
        self.config = BackupConfiguration.get_config()
        self.config.storage_type = 'LOCAL'
        self.config.local_path = 'test_backups'
        self.config.save()

    def tearDown(self):
        # Clean up test backups directory
        driver = get_storage_driver(self.config)
        test_dir = driver.directory
        if os.path.exists(test_dir):
            import shutil
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_gfs_tier_classification(self):
        # Monthly on 1st of month
        dt_monthly = datetime(2026, 11, 1, 2, 0)
        self.assertEqual(determine_gfs_tier(dt_monthly, self.config), 'MONTHLY')

        # Weekly on Sunday (weekday 6)
        dt_weekly = datetime(2026, 11, 8, 2, 0) # Sunday
        self.assertEqual(determine_gfs_tier(dt_weekly, self.config), 'WEEKLY')

        # Daily on Wednesday
        dt_daily = datetime(2026, 11, 4, 2, 0) # Wednesday
        self.assertEqual(determine_gfs_tier(dt_daily, self.config), 'DAILY')

    def test_backup_execution_and_encryption_roundtrip(self):
        # Test unencrypted backup
        self.config.encryption_passphrase = ''
        self.config.save()

        rec = execute_backup('MANUAL', self.config)
        self.assertEqual(rec.status, 'SUCCESS')
        self.assertFalse(rec.is_encrypted)
        self.assertTrue(rec.file_size > 0)

        # Test AES-256-GCM encryption
        passphrase = 'StrongPassphrase2026!'
        raw_data = b"Sample Database SQL Payload for SportsBall testing"
        encrypted = encrypt_payload(raw_data, passphrase)
        self.assertNotEqual(raw_data, encrypted)
        self.assertTrue(encrypted.startswith(b"SBALLENC1"))

        # Decrypt payload
        decrypted = decrypt_payload(encrypted, passphrase)
        self.assertEqual(raw_data, decrypted)

        # Wrong passphrase fails
        with self.assertRaises(ValueError):
            decrypt_payload(encrypted, 'WrongPassphrase!')

    def test_gfs_retention_pruning(self):
        self.config.keep_daily = 2
        self.config.save()

        # Create 4 dummy daily records
        for i in range(4):
            BackupRecord.objects.create(
                filename=f"sportsball_daily_test_{i}.sql.gz",
                tier='DAILY',
                storage_type='LOCAL',
                file_size=1024,
                status='SUCCESS'
            )

        self.assertEqual(BackupRecord.objects.filter(tier='DAILY').count(), 4)
        pruned = enforce_gfs_retention(self.config)
        self.assertEqual(len(pruned), 2)
        self.assertEqual(BackupRecord.objects.filter(tier='DAILY').count(), 2)

    def test_system_admin_least_privilege_access_control(self):
        # 1. Anonymous visitor cannot access system-admin
        resp = self.client.get(reverse('system_admin_dashboard'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp.url)

        # 2. Player cannot access system-admin
        self.client.force_login(self.player_user)
        resp = self.client.get(reverse('system_admin_dashboard'))
        self.assertEqual(resp.status_code, 302)

        # 3. League Admin cannot access system-admin (PoLP boundary)
        self.client.force_login(self.league_admin)
        resp = self.client.get(reverse('system_admin_dashboard'))
        self.assertEqual(resp.status_code, 302)

        # 4. Superuser has full access
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse('system_admin_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Platform Telemetry &amp; Diagnostics")

        resp = self.client.get(reverse('system_admin_backups'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "GFS Automated Backups &amp; Restore")

        resp = self.client.get(reverse('system_admin_users'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "User Account Controls")

    def test_maintenance_mode_middleware(self):
        setting = SystemSetting.get_settings()
        setting.maintenance_mode = True
        setting.maintenance_message = "Platform maintenance test message"
        setting.save()

        # Anonymous visitor receives 503 Service Unavailable
        self.client.logout()
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 503)
        self.assertContains(resp, "Platform maintenance test message", status_code=503)

        # Superuser bypasses 503 maintenance mode
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)

        # Reset maintenance mode
        setting.maintenance_mode = False
        setting.save()

    def test_emergency_banner_rendering(self):
        setting = SystemSetting.get_settings()
        setting.banner_active = True
        setting.banner_message = "Severe Weather Alert: All Fields Closed"
        setting.banner_link = "/announcements/"
        setting.save()

        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Severe Weather Alert: All Fields Closed")

        # Deactivate
        setting.banner_active = False
        setting.save()

    def test_user_account_controls(self):
        self.client.force_login(self.superuser)

        # Toggle deactivation
        resp = self.client.post(reverse('admin_toggle_user_active', args=[self.player_user.id]))
        self.assertEqual(resp.status_code, 302)
        self.player_user.refresh_from_db()
        self.assertFalse(self.player_user.is_active)

        # Cannot deactivate own account
        resp = self.client.post(reverse('admin_toggle_user_active', args=[self.superuser.id]))
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_active)

        # Password reset
        resp = self.client.post(reverse('admin_reset_user_password', args=[self.player_user.id]))
        self.assertEqual(resp.status_code, 302)
