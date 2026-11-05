from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import FileExtensionValidator
from django.utils import timezone


class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('player', 'Player'),
        ('coach', 'Coach / Captain'),
        ('referee', 'Referee / Scorekeeper'),
        ('admin', 'League Admin'),
    ]

    role = models.CharField(max_length=15, choices=ROLE_CHOICES, default='player')
    church = models.ForeignKey(
        'core.Church',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='members',
        help_text="Home church affiliation"
    )
    phone = models.CharField(max_length=30, blank=True)
    emergency_contact_name = models.CharField(max_length=120, blank=True)
    emergency_contact_phone = models.CharField(max_length=30, blank=True)
    jersey_number = models.PositiveIntegerField(null=True, blank=True)
    bio = models.TextField(blank=True)
    is_free_agent = models.BooleanField(
        default=False,
        help_text="Looking for a team to join"
    )
    waiver_signed = models.BooleanField(default=False)
    waiver_signed_at = models.DateTimeField(null=True, blank=True)
    waiver_signature = models.CharField(max_length=150, blank=True)

    # Walk-up song fields for Softball / Baseball
    walkup_song_title = models.CharField(
        max_length=150,
        blank=True,
        help_text="Song title & artist (e.g., 'Eye of the Tiger - Survivor')"
    )
    walkup_song_file = models.FileField(
        upload_to='walkup_songs/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=['mp3', 'wav', 'm4a', 'ogg', 'aac'])],
        help_text="Upload an audio file (MP3, WAV, M4A, OGG) for offline ballpark playback"
    )
    walkup_start_seconds = models.PositiveIntegerField(
        default=0,
        help_text="Start time in seconds where the walk-up clip should begin"
    )
    walkup_duration_seconds = models.PositiveIntegerField(
        default=12,
        help_text="How many seconds the walk-up clip should play (e.g., 12 seconds)"
    )

    def sign_waiver(self, signature_name: str):
        self.waiver_signed = True
        self.waiver_signed_at = timezone.now()
        self.waiver_signature = signature_name
        self.save(update_fields=['waiver_signed', 'waiver_signed_at', 'waiver_signature'])

    @property
    def is_league_admin(self):
        return self.role == 'admin' or self.is_superuser or self.is_staff

    @property
    def can_manage_teams(self):
        return self.role in ('admin', 'coach') or self.is_superuser or self.is_staff

    @property
    def can_record_scores(self):
        return self.role in ('admin', 'referee', 'coach') or self.is_superuser or self.is_staff

    @property
    def display_name(self):
        full = self.get_full_name().strip()
        return full if full else self.username

    def __str__(self):
        return f"{self.display_name} ({self.get_role_display()})"
