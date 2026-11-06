from django.db import models
from django.conf import settings


class Church(models.Model):
    name = models.CharField(max_length=150, unique=True)
    denomination = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    pastor_or_contact = models.CharField(max_length=120, blank=True, help_text="Primary pastor or sports ministry contact")
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    commissioner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_churches',
        help_text="Church Commissioner / Sports Director who registers teams and designates captains"
    )
    dues_paid = models.BooleanField(
        default=False,
        help_text="Has the church paid annual/season league affiliation dues?"
    )
    invite_code = models.CharField(
        max_length=32,
        unique=True,
        blank=True,
        null=True,
        help_text="Unique invite token for onboarding church pastor / sports commissioner"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.invite_code:
            import uuid
            self.invite_code = uuid.uuid4().hex[:10]
        super().save(*args, **kwargs)

    def get_invite_url(self, request=None):
        from django.urls import reverse
        rel = reverse('join_church_invite', args=[self.invite_code])
        return request.build_absolute_uri(rel) if request else rel

    class Meta:
        verbose_name_plural = "Churches"
        ordering = ['name']

    def __str__(self):
        return self.name


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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_urgent', '-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_category_display()})"
