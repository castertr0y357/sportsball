"""
AudioTrack model representing precision-clipped walk-up songs for players
and team intro/walk-on anthems across all sports, with coach/official veto moderation.
"""
from __future__ import annotations
from django.db import models
from django.conf import settings
from django.core.validators import FileExtensionValidator
from users.validators import validate_audio_file_size


class AudioTrack(models.Model):
    TRACK_TYPE_CHOICES = [
        ('player_walkup', 'Player Walk-Up Song'),
        ('team_intro', 'Team Intro Anthem'),
    ]

    STATUS_CHOICES = [
        ('approved', 'Approved / Active'),
        ('pending', 'Pending Review'),
        ('vetoed', 'Vetoed / Inappropriate'),
    ]

    track_type = models.CharField(
        max_length=20,
        choices=TRACK_TYPE_CHOICES,
        default='player_walkup',
        db_index=True
    )
    title = models.CharField(
        max_length=150,
        help_text="Song title and artist (e.g. 'Survivor - Eye of the Tiger')"
    )
    audio_file = models.FileField(
        upload_to='walkup_songs/',
        validators=[
            FileExtensionValidator(allowed_extensions=['mp3', 'wav', 'm4a', 'ogg', 'aac']),
            validate_audio_file_size,
        ],
        help_text="Audio file (MP3, WAV, M4A, OGG, max 8MB)"
    )

    # Sub-second precision timing (e.g. 13.4s)
    start_seconds = models.FloatField(
        default=0.0,
        help_text="Start offset in seconds (e.g. 45.2)"
    )
    duration_seconds = models.FloatField(
        default=12.0,
        help_text="Duration in seconds (e.g. 13.4)"
    )

    # Ownership: Player Walk-Up vs Team Intro Anthem
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='audio_tracks',
        help_text="Owning player (for player walk-ups)"
    )
    team = models.ForeignKey(
        'leagues.Team',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='intro_tracks',
        help_text="Owning team (for team intro anthems)"
    )

    # Status & Official Veto Moderation
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='approved',
        db_index=True
    )
    vetoed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vetoed_tracks'
    )
    vetoed_at = models.DateTimeField(null=True, blank=True)
    veto_reason = models.TextField(
        blank=True,
        help_text="Reason for veto recorded by coach or commissioner (e.g. Inappropriate lyrics)"
    )
    replacement_track = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='replacing_tracks',
        help_text="Approved track assigned as replacement"
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Active walk-up song for game day"
    )
    is_public_jukebox = models.BooleanField(
        default=True,
        help_text="Share to Church / League Jukebox for other members"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def end_seconds(self) -> float:
        return round(self.start_seconds + self.duration_seconds, 1)

    @property
    def is_vetoed(self) -> bool:
        return self.status == 'vetoed'

    def get_effective_playback(self) -> tuple[str, float, float]:
        """
        Returns (audio_url, start_seconds, duration_seconds).
        If vetoed, uses replacement_track if set, or empty string.
        """
        if self.is_vetoed:
            if self.replacement_track and not self.replacement_track.is_vetoed:
                return self.replacement_track.get_effective_playback()
            return ("", 0.0, 0.0)
        url = self.audio_file.url if self.audio_file else ""
        return (url, round(self.start_seconds, 1), round(self.duration_seconds, 1))

    def __str__(self):
        owner = self.user.display_name if self.user else (self.team.name if self.team else "Unassigned")
        return f"{self.title} ({self.duration_seconds:.1f}s) - {owner} [{self.get_status_display()}]"
