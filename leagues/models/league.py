"""League domain model defining sport configurations, rules, and commissioner policies."""
from __future__ import annotations
from django.db import models
from django.conf import settings


class League(models.Model):
    SPORT_CHOICES = [
        ('basketball', 'Basketball'),
        ('softball', 'Softball'),
        ('baseball', 'Baseball'),
        ('volleyball', 'Volleyball'),
        ('flag_football', 'Flag Football'),
        ('soccer', 'Soccer'),
        ('pickleball', 'Pickleball'),
        ('cornhole', 'Cornhole'),
        ('other', 'Other Fellowship Sport'),
    ]

    name = models.CharField(max_length=100)
    sport = models.CharField(max_length=30, choices=SPORT_CHOICES, default='basketball')
    description = models.TextField()
    rules = models.TextField(blank=True, help_text="League rules, sportsmanship covenant, and game format")
    discord_webhook_url = models.URLField(
        blank=True,
        help_text="Discord Webhook URL for league-wide score & rainout announcements"
    )
    # Clock toggles & settings
    enable_game_clock = models.BooleanField(
        default=False,
        help_text="Show master game/period countdown clock (typically True for basketball/football/soccer)"
    )
    default_period_minutes = models.PositiveIntegerField(
        default=20,
        help_text="Minutes per half/quarter/period (e.g., 20 for basketball/football)"
    )
    enable_flag_football_clocks = models.BooleanField(
        default=False,
        help_text="Enable Flag Football 25s play clock and QB 7s pass/rush countdown"
    )
    enable_time_limit_clock = models.BooleanField(
        default=False,
        help_text="Optional overall game limit countdown (e.g. 55-min softball limit)"
    )
    enable_timeout_clock = models.BooleanField(
        default=True,
        help_text="Enable 1-tap 30s/60s timeout countdown timer"
    )
    # League Policies: Substitutes & Minor Players
    allow_emergency_subs = models.BooleanField(
        default=False,
        help_text="Allow teams to use approved guest/substitute players to prevent regular-season forfeits."
    )
    allow_minors = models.BooleanField(
        default=False,
        help_text="Permit players under 18 to participate with verified parental guardian waiver."
    )
    # Configurable Sportsmanship Thresholds for Season Re-Invitation
    sportsmanship_good_threshold = models.DecimalField(
        max_digits=3, decimal_places=2, default=4.00,
        help_text="Minimum average score for automatic renewal invitation (e.g., 4.00)"
    )
    sportsmanship_review_threshold = models.DecimalField(
        max_digits=3, decimal_places=2, default=3.00,
        help_text="Scores between review and good threshold require committee review before re-invitation."
    )
    
    # Sport & Rule Engine Presets
    inning_run_limit = models.PositiveIntegerField(
        null=True, blank=True, default=5,
        help_text="Max runs per half-inning before automatic side retirement (e.g. 5). Leave blank for unlimited."
    )
    unlimited_runs_final_inning = models.BooleanField(
        default=True,
        help_text="Allow unlimited runs in final scheduled regulation inning (e.g. 7th inning)."
    )
    mercy_rule_tier1_runs = models.PositiveIntegerField(
        null=True, blank=True, default=20,
        help_text="Run lead for tier 1 mercy rule (e.g. 20 runs)."
    )
    mercy_rule_tier1_inning = models.PositiveIntegerField(
        null=True, blank=True, default=3,
        help_text="Inning after which tier 1 mercy rule applies (e.g. 3rd inning)."
    )
    mercy_rule_tier2_runs = models.PositiveIntegerField(
        null=True, blank=True, default=15,
        help_text="Run lead for tier 2 mercy rule (e.g. 15 runs)."
    )
    mercy_rule_tier2_inning = models.PositiveIntegerField(
        null=True, blank=True, default=4,
        help_text="Inning after which tier 2 mercy rule applies (e.g. 4th inning)."
    )
    mercy_rule_tier3_runs = models.PositiveIntegerField(
        null=True, blank=True, default=10,
        help_text="Run lead for tier 3 mercy rule (e.g. 10 runs)."
    )
    mercy_rule_tier3_inning = models.PositiveIntegerField(
        null=True, blank=True, default=5,
        help_text="Inning after which tier 3 mercy rule applies (e.g. 5th inning)."
    )
    enforce_mercy_rule_in_playoffs = models.BooleanField(
        default=False,
        help_text="Enforce mercy rules in playoff games (defaults to False so championships play out)."
    )
    softball_count_1_1_start = models.BooleanField(
        default=True,
        help_text="Batters start each plate appearance with 1 Ball and 1 Strike (church slowpitch standard)."
    )
    allow_courtesy_foul = models.BooleanField(
        default=True,
        help_text="Batters receive 1 courtesy waste foul on 2 strikes before strike 3 is called."
    )
    enable_international_tiebreaker = models.BooleanField(
        default=False,
        help_text="In extra innings, start half-innings with last out placed on 2nd base."
    )
    enable_time_limit_alert = models.BooleanField(
        default=False,
        help_text="Display warning when time limit is reached."
    )
    game_time_limit_minutes = models.PositiveIntegerField(
        default=55, null=True, blank=True,
        help_text="Scheduled game length in minutes."
    )
    no_new_inning_minutes = models.PositiveIntegerField(
        default=50, null=True, blank=True,
        help_text="Minutes mark after which no new inning may begin."
    )
    basketball_stop_clock_margin = models.PositiveIntegerField(
        default=10, null=True, blank=True,
        help_text="Point margin threshold to convert running clock to stop clock in final 2 minutes."
    )
    foul_out_limit = models.PositiveIntegerField(
        default=5,
        help_text="Personal fouls limit before player disqualification."
    )
    volleyball_set_cap = models.PositiveIntegerField(
        default=27, null=True, blank=True,
        help_text="Maximum hard score cap on standard 25-point set."
    )
    volleyball_tiebreak_cap = models.PositiveIntegerField(
        default=17, null=True, blank=True,
        help_text="Maximum hard score cap on deciding 15-point set."
    )

    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='leagues'
    )
    master_officials_pool = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='master_officiating_leagues',
        help_text="Master pool of certified officials eligible for assignment across seasons in this league"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    @property
    def is_diamond_sport(self):
        """Softball and Baseball have innings, outs, base diamonds, and at-bats."""
        return self.sport in ('softball', 'baseball')

    @property
    def score_label(self):
        """Dynamic scoring label depending on sport."""
        if self.sport in ('softball', 'baseball'):
            return "Runs"
        elif self.sport in ('soccer',):
            return "Goals"
        return "Points"

    @property
    def period_label(self):
        """Inning, Quarter, Half, or Set."""
        if self.sport in ('softball', 'baseball'):
            return "Inning"
        elif self.sport in ('basketball', 'flag_football'):
            return "Quarter / Half"
        elif self.sport in ('volleyball', 'pickleball'):
            return "Set / Game"
        elif self.sport in ('soccer',):
            return "Half"
        return "Period"

    def __str__(self):
        return f"{self.name} ({self.get_sport_display()})"


