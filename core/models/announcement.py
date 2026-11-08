"""Announcement model broadcasting updates, weather alerts, devotionals, and urgent banners."""
from __future__ import annotations
from django.db import models
from django.conf import settings


class Announcement(models.Model):
    CATEGORY_CHOICES = [
        ('general', 'General Update'),
        ('weather', 'Weather / Rainout Alert'),
        ('schedule', 'Schedule / Gym Change'),
        ('devotional', 'Weekly Devotional & Prayer'),
        ('rules', 'Rules & League Policy'),
    ]

    title = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general')
    content = models.TextField()
    scripture_reference = models.CharField(max_length=100, blank=True, help_text="Optional Bible verse reference (e.g., 1 Corinthians 9:24)")
    league = models.ForeignKey(
        'leagues.League',
        on_delete=models.CASCADE,
        related_name='announcements',
        null=True,
        blank=True,
        help_text="Leave blank for a platform-wide announcement"
    )
    season = models.ForeignKey(
        'leagues.Season',
        on_delete=models.CASCADE,
        related_name='announcements',
        null=True,
        blank=True,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authored_announcements'
    )
    is_urgent = models.BooleanField(default=False, help_text="Pin to dashboard as top priority notice")
    send_discord = models.BooleanField(default=False, help_text="Broadcast to league Discord channel")
    send_sms = models.BooleanField(default=False, help_text="Send urgent SMS via Twilio to players")
    is_banner = models.BooleanField(default=False, help_text="Display as persistent top-of-screen alert banner")
    banner_active = models.BooleanField(default=True, help_text="Show banner across pages until dismissed or deactivated")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_urgent', '-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_category_display()})"

