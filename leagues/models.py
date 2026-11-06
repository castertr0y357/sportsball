from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError


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
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='leagues'
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


class Season(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name='seasons')
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    current = models.BooleanField(default=False)
    registration_open = models.BooleanField(default=True)
    registration_fee = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    max_roster_size = models.PositiveIntegerField(default=15)
    discord_webhook_url = models.URLField(
        blank=True,
        help_text="Discord Webhook URL for this specific season"
    )
    venmo_handle = models.CharField(
        max_length=60,
        blank=True,
        help_text="Venmo username for dues (e.g. @GraceChurchSports)"
    )
    cashapp_handle = models.CharField(
        max_length=60,
        blank=True,
        help_text="CashApp handle for dues (e.g. $GraceLeague)"
    )
    paypal_link = models.URLField(
        blank=True,
        help_text="Direct PayPal.me link (e.g. https://paypal.me/gracechurch)"
    )

    class Meta:
        ordering = ['-current', '-start_date']

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("Season end date cannot be earlier than start date.")

    def get_standings(self):
        """
        Calculate and return ordered standings for all teams in this season.
        Returns a list of dicts with:
          team, played, wins, losses, ties, win_pct, points_for, points_against, point_diff, streak
        """
        teams = list(self.teams.select_related('church', 'captain').all())
        stats_map = {
            team.id: {
                'team': team,
                'played': 0,
                'wins': 0,
                'losses': 0,
                'ties': 0,
                'win_pct': 0.0,
                'points_for': 0,
                'points_against': 0,
                'point_diff': 0,
                'results': [],
            }
            for team in teams
        }

        completed_games = self.games.filter(
            status='completed',
            game_type='regular'
        ).order_by('date', 'id')

        for game in completed_games:
            t1_id = game.team1_id
            t2_id = game.team2_id
            s1 = game.team1_score or 0
            s2 = game.team2_score or 0

            if t1_id in stats_map:
                st1 = stats_map[t1_id]
                st1['played'] += 1
                st1['points_for'] += s1
                st1['points_against'] += s2
                if s1 > s2:
                    st1['wins'] += 1
                    st1['results'].append('W')
                elif s1 < s2:
                    st1['losses'] += 1
                    st1['results'].append('L')
                else:
                    st1['ties'] += 1
                    st1['results'].append('T')

            if t2_id in stats_map:
                st2 = stats_map[t2_id]
                st2['played'] += 1
                st2['points_for'] += s2
                st2['points_against'] += s1
                if s2 > s1:
                    st2['wins'] += 1
                    st2['results'].append('W')
                elif s2 < s1:
                    st2['losses'] += 1
                    st2['results'].append('L')
                else:
                    st2['ties'] += 1
                    st2['results'].append('T')

        standings = []
        for entry in stats_map.values():
            played = entry['played']
            if played > 0:
                entry['win_pct'] = round((entry['wins'] + 0.5 * entry['ties']) / played, 3)
            entry['point_diff'] = entry['points_for'] - entry['points_against']

            results = entry['results']
            if not results:
                entry['streak'] = '-'
            else:
                last = results[-1]
                count = 0
                for r in reversed(results):
                    if r == last:
                        count += 1
                    else:
                        break
                entry['streak'] = f"{last}{count}"
            standings.append(entry)

        standings.sort(
            key=lambda x: (x['win_pct'], x['wins'], x['point_diff'], x['points_for'], x['team'].name),
            reverse=True
        )
        for idx, row in enumerate(standings, start=1):
            row['rank'] = idx
        return standings

    def __str__(self):
        return f"{self.league.name} - {self.name}"


class Team(models.Model):
    name = models.CharField(max_length=100)
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name='teams')
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='teams')
    church = models.ForeignKey(
        'core.Church',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='teams',
        help_text="Sponsoring or home church"
    )
    captain = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='captained_teams',
        limit_choices_to={'role__in': ['admin', 'coach', 'player']}
    )
    players = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='teams',
        blank=True
    )
    team_color = models.CharField(max_length=50, blank=True, default='Navy Blue')
    dues_paid = models.BooleanField(default=False, help_text="Has team registration fee been paid?")
    invite_code = models.CharField(
        max_length=32,
        unique=True,
        blank=True,
        null=True,
        db_index=True,
        help_text="Unique 1-tap player invite code"
    )

    class Meta:
        ordering = ['name']
        unique_together = [('season', 'name')]

    def save(self, *args, **kwargs):
        if not self.invite_code:
            import secrets
            self.invite_code = secrets.token_urlsafe(8)
        if self.season_id and not self.league_id:
            self.league = self.season.league
        super().save(*args, **kwargs)

    def get_invite_url(self, request=None):
        from django.urls import reverse
        if not self.invite_code:
            import secrets
            self.invite_code = secrets.token_urlsafe(8)
            self.save(update_fields=['invite_code'])
        path = reverse('join_team_invite', kwargs={'invite_code': self.invite_code})
        if request:
            return request.build_absolute_uri(path)
        return path

    def __str__(self):
        return f"{self.name} ({self.season.name})"


class SeasonRegistration(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Assignment / Approval'),
        ('approved', 'Approved / Rostered'),
        ('declined', 'Declined'),
    ]

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='registrations')
    player = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='season_registrations')
    preferred_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registration_requests',
        help_text="Leave blank to register as a Free Agent"
    )
    is_free_agent = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    waiver_agreed = models.BooleanField(default=False)
    dues_paid = models.BooleanField(default=False)
    notes = models.CharField(max_length=255, blank=True, help_text="Skill level, position preference, or availability notes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('season', 'player')]
        ordering = ['-created_at']

    def __str__(self):
        target = self.preferred_team.name if self.preferred_team else "Free Agent"
        return f"{self.player.username} -> {self.season.name} ({target})"


class Game(models.Model):
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed / Final'),
        ('postponed', 'Postponed / Rainout'),
        ('cancelled', 'Cancelled'),
    ]

    GAME_TYPE_CHOICES = [
        ('regular', 'Regular Season'),
        ('playoff_qf', 'Playoff Quarterfinal'),
        ('playoff_sf', 'Playoff Semifinal'),
        ('playoff_final', 'Championship Final'),
        ('consolation', '3rd Place / Fellowship Consolation'),
    ]

    INNING_HALF_CHOICES = [
        ('top', 'Top (Away Batting)'),
        ('bottom', 'Bottom (Home Batting)'),
    ]

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='games', null=True, blank=True)
    team1 = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='games_as_team1', verbose_name="Home Team")
    team2 = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='games_as_team2', verbose_name="Away Team")
    date = models.DateTimeField()
    location = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    game_type = models.CharField(max_length=20, choices=GAME_TYPE_CHOICES, default='regular')
    week_number = models.PositiveIntegerField(default=1)
    playoff_seed1 = models.PositiveIntegerField(null=True, blank=True)
    playoff_seed2 = models.PositiveIntegerField(null=True, blank=True)
    team1_score = models.PositiveIntegerField(default=0)
    team2_score = models.PositiveIntegerField(default=0)
    team1_hits = models.PositiveIntegerField(default=0)
    team2_hits = models.PositiveIntegerField(default=0)

    # Live Dugout / Diamond State (Simplified GameChanger replacement)
    current_inning = models.PositiveIntegerField(default=1)
    inning_half = models.CharField(max_length=10, choices=INNING_HALF_CHOICES, default='top')
    outs = models.PositiveIntegerField(default=0)
    runner_on_first = models.BooleanField(default=False)
    runner_on_second = models.BooleanField(default=False)
    runner_on_third = models.BooleanField(default=False)
    team1_batter_index = models.PositiveIntegerField(default=0)
    team2_batter_index = models.PositiveIntegerField(default=0)
    current_batter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='games_currently_batting'
    )
    play_by_play = models.JSONField(default=list, blank=True)

    result = models.JSONField(blank=True, null=True)
    stats = models.JSONField(blank=True, null=True)
    notes = models.TextField(blank=True)

    # Master Clock live state (synced with GameCast)
    clock_seconds_remaining = models.IntegerField(default=1200)
    clock_running = models.BooleanField(default=False)
    clock_last_started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['date', 'id']

    def clean(self):
        if self.team1_id and self.team2_id and self.team1_id == self.team2_id:
            raise ValidationError("A team cannot play against itself.")

    def save(self, *args, **kwargs):
        if not self.season_id and self.team1_id:
            self.season = self.team1.season
        if self.status == 'completed':
            winner = None
            if self.team1_score > self.team2_score:
                winner = self.team1.name
            elif self.team2_score > self.team1_score:
                winner = self.team2.name
            else:
                winner = 'Tie'
            self.result = {
                'team1_score': self.team1_score,
                'team2_score': self.team2_score,
                'winner': winner,
            }
        super().save(*args, **kwargs)

    @property
    def batting_team(self):
        """Top of inning = Away (team2) bats; Bottom of inning = Home (team1) bats."""
        return self.team2 if self.inning_half == 'top' else self.team1

    def ensure_lineups_initialized(self):
        """Auto-initialize GameLineupEntry rows from each team's roster if not yet set."""
        for team in (self.team1, self.team2):
            if not self.lineup_entries.filter(team=team).exists():
                for idx, player in enumerate(team.players.all().order_by('id'), start=1):
                    GameLineupEntry.objects.create(
                        game=self,
                        team=team,
                        player=player,
                        batting_order=idx,
                        is_present=True,
                    )

    def get_active_lineup(self, team):
        """Return ordered GameLineupEntry queryset of present players for a team."""
        return list(
            self.lineup_entries.filter(team=team, is_present=True)
            .select_related('player')
            .order_by('batting_order', 'id')
        )

    def advance_to_next_batter(self):
        """
        Advance the batting team's pointer to the next present player in the batting order,
        skipping anyone checked out as absent. Updates self.current_batter and returns that user.
        """
        team = self.batting_team
        active_entries = self.get_active_lineup(team)
        if not active_entries:
            self.current_batter = None
            return None

        if team == self.team1:
            idx = self.team1_batter_index % len(active_entries)
            next_entry = active_entries[idx]
            self.team1_batter_index = (idx + 1) % len(active_entries)
        else:
            idx = self.team2_batter_index % len(active_entries)
            next_entry = active_entries[idx]
            self.team2_batter_index = (idx + 1) % len(active_entries)

        self.current_batter = next_entry.player
        return self.current_batter

    def peek_on_deck_batter(self):
        """Return the player who is on deck (up next after current_batter) for the batting team."""
        team = self.batting_team
        active_entries = self.get_active_lineup(team)
        if not active_entries:
            return None
        idx = (self.team1_batter_index if team == self.team1 else self.team2_batter_index) % len(active_entries)
        return active_entries[idx].player

    def get_team_rsvp_summary(self, team):
        """Returns headcount breakdown of RSVPs for players on this team."""
        roster_ids = list(team.players.values_list('id', flat=True))
        rsvps = {r.player_id: r.response for r in self.rsvps.filter(player_id__in=roster_ids)}
        yes_count = sum(1 for resp in rsvps.values() if resp == 'yes')
        no_count = sum(1 for resp in rsvps.values() if resp == 'no')
        maybe_count = sum(1 for resp in rsvps.values() if resp == 'maybe')
        total_roster = len(roster_ids)
        pending_count = total_roster - len(rsvps)
        return {
            'yes': yes_count,
            'no': no_count,
            'maybe': maybe_count,
            'pending': pending_count,
            'total': total_roster,
        }

    def get_player_rsvp(self, player):
        if not player or not player.is_authenticated:
            return None
        rsvp = self.rsvps.filter(player=player).first()
        return rsvp.response if rsvp else None

    def log_play(self, message: str):
        log = list(self.play_by_play or [])
        half_label = "Top" if self.inning_half == 'top' else "Bot"
        entry = f"[{half_label} {self.current_inning}] {message}"
        log.insert(0, entry)
        self.play_by_play = log[:25]

    @property
    def winner(self):
        if self.status != 'completed':
            return None
        if self.team1_score > self.team2_score:
            return self.team1
        elif self.team2_score > self.team1_score:
            return self.team2
        return None

    def __str__(self):
        if self.status == 'completed':
            return f"{self.team1.name} ({self.team1_score}) vs {self.team2.name} ({self.team2_score})"
        return f"{self.team1.name} vs {self.team2.name} ({self.date.strftime('%b %d, %Y')})"


class GameLineupEntry(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='lineup_entries')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='game_lineups')
    player = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='lineup_appearances')
    batting_order = models.PositiveIntegerField(default=1)
    is_present = models.BooleanField(default=True, help_text="Checked in / present at the ballpark today")
    field_position = models.CharField(max_length=120, blank=True, help_text="e.g., SS / P or primary position")
    position_rotations = models.JSONField(default=dict, blank=True, help_text="Inning or period rotations (e.g. {'1': 'SS', '2': 'P'})")

    class Meta:
        ordering = ['team', 'batting_order', 'id']
        unique_together = [('game', 'team', 'player')]

    def get_position_for_inning(self, inning: int) -> str:
        """Returns the specific position for this inning, or fallback to field_position."""
        if self.position_rotations:
            pos = self.position_rotations.get(str(inning))
            if pos:
                return pos
        return self.field_position or '-'

    def __str__(self):
        status = "Present" if self.is_present else "Absent (Skipped)"
        return f"#{self.batting_order} {self.player.display_name} ({self.team.name}) [{self.field_position}] - {status}"


class GameRSVP(models.Model):
    RESPONSE_CHOICES = [
        ('yes', 'In'),
        ('no', 'Out'),
        ('maybe', 'Maybe'),
    ]
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='rsvps')
    player = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='game_rsvps')
    response = models.CharField(max_length=10, choices=RESPONSE_CHOICES, default='yes')
    notes = models.CharField(max_length=150, blank=True, help_text="e.g. Running 10 mins late")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = [('game', 'player')]

    def __str__(self):
        return f"{self.player.display_name} -> {self.get_response_display()} ({self.game})"
