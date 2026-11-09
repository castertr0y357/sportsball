import random
from django.db import models
from django.core.validators import FileExtensionValidator
from users.models.user import validate_audio_file_size


class VoicePack(models.Model):
    """
    Announcer persona assigned to a league or sport (e.g. Bob Uecker, NBA Jam, John Madden).
    """
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    sport = models.CharField(
        max_length=30,
        default='softball',
        help_text="Sport this voice pack is targeted for (or 'all')"
    )
    description = models.TextField(blank=True)
    author = models.CharField(max_length=120, blank=True, help_text="Creator or voice model source")
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(
        default=False,
        help_text="Default voice pack for its sport when none is specifically chosen"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sport', 'name']

    def __str__(self):
        default_tag = " (Default)" if self.is_default else ""
        return f"{self.name} [{self.sport.title()}]{default_tag}"

    def save(self, *args, **kwargs):
        if self.is_default:
            # Enforce single default per sport
            VoicePack.objects.filter(sport=self.sport, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def get_clip(self, event_type: str, situational_tag: str = 'generic'):
        """
        Retrieves a clip matching (event_type, situational_tag), falling back to (event_type, 'generic').
        Returns None if no matching clip exists.
        """
        # 1. Try specific situational tag
        candidates = list(self.clips.filter(event_type=event_type, situational_tag=situational_tag))
        if candidates:
            return random.choice(candidates)
        # 2. Fall back to generic
        if situational_tag != 'generic':
            generic_candidates = list(self.clips.filter(event_type=event_type, situational_tag='generic'))
            if generic_candidates:
                return random.choice(generic_candidates)
        return None


class VoiceClip(models.Model):
    """
    Individual audio snippet for an announcer pack (e.g. walk, strikeout, home run).
    """
    voice_pack = models.ForeignKey(VoicePack, on_delete=models.CASCADE, related_name='clips')
    event_type = models.CharField(
        max_length=50,
        db_index=True,
        help_text="e.g., batter_intro, walk, strikeout, single, double, triple, home_run, error, pickle_rundown"
    )
    situational_tag = models.CharField(
        max_length=50,
        default='generic',
        db_index=True,
        help_text="e.g. generic, bases_loaded, two_outs, clutch, lead_change, blowout"
    )
    audio_file = models.FileField(
        upload_to='voice_packs/',
        validators=[
            FileExtensionValidator(allowed_extensions=['mp3', 'wav', 'm4a', 'ogg', 'aac']),
            validate_audio_file_size,
        ]
    )
    audio_duration = models.FloatField(default=0.0, help_text="Duration in seconds")
    transcript = models.CharField(max_length=255, blank=True, help_text="Spoken phrase text")
    play_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['voice_pack', 'event_type', 'situational_tag']

    def __str__(self):
        return f"{self.voice_pack.name} - {self.event_type} ({self.situational_tag}): '{self.transcript[:30]}'"


class SoundboardEffect(models.Model):
    """
    One-touch stadium atmosphere & chaos sound effect (Yakety Sax, Organ Charge, Foghorn, etc.).
    """
    CATEGORY_CHOICES = [
        ('chaos', 'Chaos & Comedy'),
        ('rally', 'Rally & Crowd'),
        ('celebration', 'Big Celebration'),
        ('stinger', 'Short Stinger'),
    ]

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='chaos')
    icon = models.CharField(max_length=20, default='🎵', help_text="Emoji or icon code")
    audio_file = models.FileField(
        upload_to='soundboard/',
        validators=[
            FileExtensionValidator(allowed_extensions=['mp3', 'wav', 'm4a', 'ogg', 'aac']),
            validate_audio_file_size,
        ]
    )
    audio_duration = models.FloatField(default=0.0, help_text="Duration in seconds")
    loop_mode = models.BooleanField(
        default=False,
        help_text="Whether this track loops continuously until stopped (e.g. Yakety Sax rundown)"
    )
    hotkey = models.CharField(max_length=10, blank=True, help_text="Optional keyboard shortcut key (e.g. 'P', 'C')")
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return f"{self.icon} {self.name} ({self.get_category_display()})"
