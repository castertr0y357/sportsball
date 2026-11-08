"""SystemSetting, BackupConfiguration, and BackupRecord models managing ops, maintenance, and backups."""
from __future__ import annotations
import uuid
from django.db import models
from django.conf import settings


class SystemSetting(models.Model):
    maintenance_mode = models.BooleanField(default=False, help_text="Put site in maintenance mode for non-admin visitors")
    maintenance_message = models.TextField(
        default="SportsBall is undergoing brief scheduled maintenance. We will be right back!",
        help_text="Message displayed to visitors during maintenance"
    )
    banner_message = models.CharField(max_length=255, blank=True, help_text="Global top alert banner message")
    banner_link = models.CharField(max_length=255, blank=True, help_text="Optional link to view full announcement")
    banner_active = models.BooleanField(default=False, help_text="Display global emergency banner")

    @classmethod
    def get_settings(cls):
        s = cls.objects.first()
        if not s:
            s = cls.objects.create()
        return s

    def __str__(self):
        return f"System Settings (Maintenance: {'ON' if self.maintenance_mode else 'OFF'})"


class BackupConfiguration(models.Model):
    STORAGE_TYPE_CHOICES = [
        ('LOCAL', 'Local Container Volume (/backups)'),
        ('S3', 'Amazon S3 / S3-Compatible Object Storage'),
        ('CIFS', 'CIFS / SMB Windows Network Share'),
        ('NFS', 'Direct Userspace NFS Export'),
    ]
    WEEKDAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    is_enabled = models.BooleanField(default=False, help_text="Enable scheduled automated backups.")
    backup_time = models.CharField(max_length=5, default="02:00", help_text="UTC time of daily execution (HH:MM).")
    weekly_day = models.IntegerField(choices=WEEKDAY_CHOICES, default=6, help_text="Day of the week for weekly promotion (default: Sunday).")
    monthly_day = models.PositiveSmallIntegerField(default=1, help_text="Day of the month (1-28) for monthly promotion.")
    keep_daily = models.PositiveIntegerField(default=7, help_text="Number of daily backups to retain.")
    keep_weekly = models.PositiveIntegerField(default=4, help_text="Number of weekly backups to retain.")
    keep_monthly = models.PositiveIntegerField(default=3, help_text="Number of monthly backups to retain.")
    preserve_config_on_restore = models.BooleanField(default=True, help_text="Preserve active backup schedule and credentials when restoring an older snapshot.")
    
    storage_type = models.CharField(max_length=10, choices=STORAGE_TYPE_CHOICES, default='LOCAL')
    local_path = models.CharField(max_length=255, default='backups', help_text="Local directory path.")
    
    # S3
    s3_endpoint_url = models.CharField(max_length=255, blank=True, null=True, help_text="Optional custom endpoint (e.g. MinIO, Cloudflare R2).")
    s3_bucket = models.CharField(max_length=100, blank=True, default='')
    s3_region = models.CharField(max_length=50, blank=True, default='us-east-1')
    s3_access_key = models.CharField(max_length=255, blank=True, default='')
    s3_secret_key = models.CharField(max_length=255, blank=True, default='')
    s3_prefix = models.CharField(max_length=100, blank=True, default='sportsball/')

    # CIFS/SMB
    cifs_server = models.CharField(max_length=255, blank=True, default='', help_text="Hostname or IP of SMB server.")
    cifs_share = models.CharField(max_length=100, blank=True, default='', help_text="SMB share name.")
    cifs_subpath = models.CharField(max_length=255, blank=True, default='', help_text="Subfolder within share.")
    cifs_username = models.CharField(max_length=100, blank=True, default='')
    cifs_password = models.CharField(max_length=255, blank=True, default='')
    cifs_domain = models.CharField(max_length=100, blank=True, default='')

    # NFS
    nfs_server = models.CharField(max_length=255, blank=True, default='', help_text="Hostname or IP of NFS server.")
    nfs_export = models.CharField(max_length=255, blank=True, default='', help_text="NFS export path.")
    nfs_subpath = models.CharField(max_length=255, blank=True, default='', help_text="Subfolder within export.")

    encryption_passphrase = models.CharField(max_length=255, blank=True, default='', help_text="Optional passphrase to encrypt backups with AES-256-GCM.")
    webhook_url = models.URLField(blank=True, default='', help_text="Webhook URL (Discord, Gotify, Slack) for backup failure alerts.")
    last_run_at = models.DateTimeField(blank=True, null=True)
    last_status = models.CharField(max_length=20, blank=True, default='')
    last_error = models.TextField(blank=True, default='')

    class Meta:
        verbose_name_plural = "Backup Configurations"

    @classmethod
    def get_config(cls):
        cfg = cls.objects.first()
        if not cfg:
            cfg = cls.objects.create()
        return cfg

    def __str__(self):
        return f"Backup Config ({self.get_storage_type_display()}) - {'Enabled' if self.is_enabled else 'Disabled'}"


class BackupRecord(models.Model):
    TIER_CHOICES = [
        ('MANUAL', 'Manual'),
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
    ]
    STATUS_CHOICES = [
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
    ]

    import uuid
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filename = models.CharField(max_length=255, db_index=True)
    tier = models.CharField(max_length=10, choices=TIER_CHOICES, default='MANUAL')
    storage_type = models.CharField(max_length=10, choices=BackupConfiguration.STORAGE_TYPE_CHOICES, default='LOCAL')
    file_size = models.BigIntegerField(default=0, help_text="File size in bytes.")
    is_encrypted = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='SUCCESS')
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.filename} ({self.get_tier_display()} - {self.status})"
