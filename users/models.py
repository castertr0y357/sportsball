from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import FileExtensionValidator
from django.utils import timezone


class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('player', 'Player'),
        ('coach', 'Team Captain / Coach'),
        ('church_admin', 'Church Commissioner'),
        ('referee', 'Referee / Scorekeeper'),
        ('league_admin', 'League Commissioner'),
        ('committee', 'Program Committee'),
        ('admin', 'Overall Commissioner'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='player')
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
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other / Unspecified'),
    ]
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, default='')
    preferred_position = models.CharField(max_length=50, blank=True, help_text="e.g. Shortstop, 1st Base, Setter")
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
    def is_overall_commissioner(self):
        """Cross-league management: creates leagues, invites churches, approves bylaws."""
        return self.role in ('admin', 'committee') or self.is_superuser or self.is_staff

    @property
    def is_league_admin(self):
        """Covers Overall Commissioners, Committee, and League-level admins."""
        return self.role in ('admin', 'committee', 'league_admin') or self.is_superuser or self.is_staff

    @property
    def is_church_commissioner(self):
        """Covers Church Commissioners who represent/lead a church sports program."""
        return (
            self.is_overall_commissioner or
            self.role == 'church_admin' or
            self.managed_churches.exists()
        )

    def can_manage_church(self, church):
        if not church:
            return False
        if self.is_overall_commissioner:
            return True
        return (
            church.commissioner_id == self.id or
            (self.church_id == church.id and self.role == 'church_admin')
        )

    def can_manage_league(self, league):
        if not league:
            return False
        if self.is_overall_commissioner:
            return True
        return league.admin_id == self.id

    def can_manage_team(self, team):
        if not team or not self.is_authenticated:
            return False
        if self.is_overall_commissioner:
            return True
        if team.league and self.can_manage_league(team.league):
            return True
        if team.church and self.can_manage_church(team.church):
            return True
        return team.captain_id == self.id

    @property
    def can_manage_teams(self):
        return (
            self.is_league_admin or
            self.is_church_commissioner or
            self.role == 'coach' or
            self.captained_teams.exists()
        )

    @property
    def can_record_scores(self):
        return (
            self.is_league_admin or
            self.role in ('referee', 'coach') or
            self.captained_teams.exists()
        )

    def can_score_game(self, game):
        if not game or not self.is_authenticated:
            return False
        if self.is_overall_commissioner:
            return True
        if game.season and game.season.league and self.can_manage_league(game.season.league):
            return True
        if self.role == 'referee':
            return True
        if (game.team1 and game.team1.captain_id == self.id) or (game.team2 and game.team2.captain_id == self.id):
            return True
        if game.team1 and self.can_manage_church(game.team1.church):
            return True
        if game.team2 and self.can_manage_church(game.team2.church):
            return True
        return False

    @property
    def display_name(self):
        full = self.get_full_name().strip()
        return full if full else self.username

    def __str__(self):
        return f"{self.display_name} ({self.get_role_display()})"
