"""Game model storing match schedules, scores, live dugout states, clocks, and score audits."""
from __future__ import annotations
from datetime import timedelta
from django.db import models, transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone


class Game(models.Model):
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('pending_confirmation', 'Pending Opponent Confirmation'),
        ('completed', 'Completed / Final'),
        ('disputed', 'Disputed Score'),
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

    season = models.ForeignKey('Season', on_delete=models.CASCADE, related_name='games', null=True, blank=True)
    voice_pack = models.ForeignKey(
        'leagues.VoicePack',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='games',
        help_text="Custom announcer voice pack for this game (overrides league default)"
    )
    venue = models.ForeignKey('LeagueVenue', on_delete=models.SET_NULL, null=True, blank=True, related_name='scheduled_games')
    team1 = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='games_as_team1', verbose_name="Home Team")
    team2 = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='games_as_team2', verbose_name="Away Team")
    date = models.DateTimeField(db_index=True)
    location = models.CharField(max_length=200)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='scheduled', db_index=True)
    game_type = models.CharField(max_length=20, choices=GAME_TYPE_CHOICES, default='regular', db_index=True)
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

    # Active Scorer Lock (Prevents simultaneous double-scoring in Dugout Console)
    active_scorer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='active_scoring_games',
        help_text="User actively recording plays for this game in the Dugout Console"
    )
    active_scorer_expires_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when active scoring lock expires")

    # Score Confirmation, Peer Verification & Audit Trail
    score_submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='submitted_game_scores',
        help_text="User who submitted final score"
    )
    score_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_game_scores',
        help_text="User who confirmed final score"
    )
    score_submitted_at = models.DateTimeField(null=True, blank=True)
    score_confirmed = models.BooleanField(default=False, help_text="Has score been confirmed or certified by official?")
    score_dispute_notes = models.TextField(blank=True, help_text="Notes from coach or commissioner if score was disputed")
    score_audit_log = models.JSONField(default=list, blank=True, help_text="Audit log of score changes, submissions, and confirmations")

    
    # Count, Pitching & Ball/Strike State (Diamond Sports)
    current_half_runs = models.PositiveIntegerField(default=0)

    balls = models.PositiveIntegerField(default=0)
    strikes = models.PositiveIntegerField(default=0)
    courtesy_foul_used = models.BooleanField(default=False)

    # Undo Stack (Last 10 Game State Snapshots)
    play_by_play_snapshots = models.JSONField(default=list, blank=True)

    # Court Sports: Basketball Fouls & Timeouts
    team1_fouls = models.PositiveIntegerField(default=0)
    team2_fouls = models.PositiveIntegerField(default=0)
    team1_timeouts_remaining = models.PositiveIntegerField(default=3)
    team2_timeouts_remaining = models.PositiveIntegerField(default=3)

    # Court Sports: Volleyball Sets & Serving
    volleyball_sets = models.JSONField(default=list, blank=True)
    current_set = models.PositiveIntegerField(default=1)
    volleyball_serving_team = models.ForeignKey(
        'Team',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='games_currently_serving'
    )

    # Official Forfeits
    is_forfeit = models.BooleanField(default=False)
    forfeit_winner = models.ForeignKey(
        'Team',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='games_won_by_forfeit'
    )

    class Meta:
        ordering = ['date', 'id']
        indexes = [
            models.Index(fields=['season', 'status', 'date'], name='game_season_status_date_idx'),
        ]

    def clean(self):
        if self.team1_id and self.team2_id and self.team1_id == self.team2_id:
            raise ValidationError("A team cannot play against itself.")

    def save(self, *args, **kwargs):
        if not self.season_id and self.team1_id:
            self.season = self.team1.season
        if self.status == 'completed':
            self.decrement_disciplinary_suspensions()
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
                    from leagues.models.lineup import GameLineupEntry
                    GameLineupEntry.objects.create(
                        game=self,
                        team=team,
                        player=player,
                        batting_order=idx,
                        is_present=True,
                    )
        self.sync_shorthanded_automatic_outs()

    def get_effective_voice_pack(self):
        """
        Resolves effective announcer voice pack: game override -> league default -> sport default.
        """
        from .voice_announcer import VoicePack
        if self.voice_pack and self.voice_pack.is_active:
            return self.voice_pack
        if self.season and self.season.league and self.season.league.voice_pack and self.season.league.voice_pack.is_active:
            return self.season.league.voice_pack
        sport = self.season.league.sport if (self.season and self.season.league) else 'softball'
        return VoicePack.objects.filter(sport=sport, is_default=True, is_active=True).first() or VoicePack.objects.filter(is_default=True, is_active=True).first()

    def get_active_lineup(self, team):
        """Return ordered GameLineupEntry queryset of present players for a team."""
        return list(
            self.lineup_entries.filter(team=team, is_present=True)
            .select_related('player')
            .order_by('batting_order', 'id')
        )

    def sync_shorthanded_automatic_outs(self) -> dict[str, Any]:
        """
        Enforces church softball short-handed 1-out differential rule:
        - If team1_count == team2_count: 0 automatic outs for both teams (e.g. 8 vs 8, 9 vs 9, 10 vs 10).
        - If team1_count < team2_count and team1_count < 10:
          Team 1 takes exactly ONE automatic out at the end of its batting order (Spot N1 + 1). Team 2 takes 0 outs.
        - If team2_count < team1_count and team2_count < 10:
          Team 2 takes exactly ONE automatic out at the end of its batting order (Spot N2 + 1). Team 1 takes 0 outs.
        - If both teams >= 10: 0 automatic outs.
        """
        from leagues.models.lineup import GameLineupEntry
        sport = (self.season.league.sport if self.season and self.season.league else '').lower()
        if sport not in ('softball', 'baseball'):
            return {'team1_penalty': False, 'team2_penalty': False}

        # Clear existing automatic out slots to recalculate accurately
        self.lineup_entries.filter(is_automatic_out=True).delete()

        t1_present = self.lineup_entries.filter(team=self.team1, is_present=True, is_automatic_out=False).count()
        t2_present = self.lineup_entries.filter(team=self.team2, is_present=True, is_automatic_out=False).count()

        t1_penalty = False
        t2_penalty = False
        t1_spot = None
        t2_spot = None

        if t1_present < t2_present and t1_present < 10:
            t1_penalty = True
            t1_spot = t1_present + 1
            GameLineupEntry.objects.create(
                game=self,
                team=self.team1,
                player=None,
                batting_order=t1_spot,
                is_present=True,
                is_automatic_out=True,
                field_position='OUT',
                vacant_label=f"Vacant Spot #{t1_spot} (Automatic Out)"
            )
        elif t2_present < t1_present and t2_present < 10:
            t2_penalty = True
            t2_spot = t2_present + 1
            GameLineupEntry.objects.create(
                game=self,
                team=self.team2,
                player=None,
                batting_order=t2_spot,
                is_present=True,
                is_automatic_out=True,
                field_position='OUT',
                vacant_label=f"Vacant Spot #{t2_spot} (Automatic Out)"
            )

        return {
            'team1_penalty': t1_penalty,
            'team2_penalty': t2_penalty,
            'team1_count': t1_present,
            'team2_count': t2_present,
            'penalty_spot_team1': t1_spot,
            'penalty_spot_team2': t2_spot,
        }

    
    def push_snapshot(self):
        """Save a snapshot of current game state into play_by_play_snapshots (max 10)."""
        snapshot = {
            'team1_score': self.team1_score,
            'team2_score': self.team2_score,
            'team1_hits': self.team1_hits,
            'team2_hits': self.team2_hits,
            'outs': self.outs,
            'runner_on_first': self.runner_on_first,
            'runner_on_second': self.runner_on_second,
            'runner_on_third': self.runner_on_third,
            'current_half_runs': self.current_half_runs,

            'balls': self.balls,
            'strikes': self.strikes,
            'courtesy_foul_used': self.courtesy_foul_used,
            'current_inning': self.current_inning,
            'inning_half': self.inning_half,
            'team1_batter_index': self.team1_batter_index,
            'team2_batter_index': self.team2_batter_index,
            'current_batter_id': self.current_batter_id,
            'clock_seconds_remaining': self.clock_seconds_remaining,
            'clock_running': self.clock_running,
            'team1_fouls': self.team1_fouls,
            'team2_fouls': self.team2_fouls,
            'team1_timeouts_remaining': self.team1_timeouts_remaining,
            'team2_timeouts_remaining': self.team2_timeouts_remaining,
            'current_set': self.current_set,
            'volleyball_sets': list(self.volleyball_sets or []),
            'status': self.status,
            'play_log_count': len(self.play_by_play or []),
        }
        snapshots = list(self.play_by_play_snapshots or [])
        snapshots.append(snapshot)
        if len(snapshots) > 10:
            snapshots = snapshots[-10:]
        self.play_by_play_snapshots = snapshots

    def pop_snapshot(self):
        """Restore previous snapshot and remove corresponding play log entry. Returns True if restored."""
        snapshots = list(self.play_by_play_snapshots or [])
        if not snapshots:
            return False
        snap = snapshots.pop()
        self.team1_score = snap.get('team1_score', self.team1_score)
        self.team2_score = snap.get('team2_score', self.team2_score)
        self.team1_hits = snap.get('team1_hits', self.team1_hits)
        self.team2_hits = snap.get('team2_hits', self.team2_hits)
        self.outs = snap.get('outs', self.outs)
        self.runner_on_first = snap.get('runner_on_first', self.runner_on_first)
        self.runner_on_second = snap.get('runner_on_second', self.runner_on_second)
        self.runner_on_third = snap.get('runner_on_third', self.runner_on_third)
        self.current_half_runs = snap.get('current_half_runs', self.current_half_runs)

        self.balls = snap.get('balls', self.balls)
        self.strikes = snap.get('strikes', self.strikes)
        self.courtesy_foul_used = snap.get('courtesy_foul_used', self.courtesy_foul_used)
        self.current_inning = snap.get('current_inning', self.current_inning)
        self.inning_half = snap.get('inning_half', self.inning_half)
        self.team1_batter_index = snap.get('team1_batter_index', self.team1_batter_index)
        self.team2_batter_index = snap.get('team2_batter_index', self.team2_batter_index)
        self.current_batter_id = snap.get('current_batter_id', self.current_batter_id)
        self.clock_seconds_remaining = snap.get('clock_seconds_remaining', self.clock_seconds_remaining)
        self.clock_running = snap.get('clock_running', self.clock_running)
        self.team1_fouls = snap.get('team1_fouls', self.team1_fouls)
        self.team2_fouls = snap.get('team2_fouls', self.team2_fouls)
        self.team1_timeouts_remaining = snap.get('team1_timeouts_remaining', self.team1_timeouts_remaining)
        self.team2_timeouts_remaining = snap.get('team2_timeouts_remaining', self.team2_timeouts_remaining)
        self.current_set = snap.get('current_set', self.current_set)
        self.volleyball_sets = snap.get('volleyball_sets', self.volleyball_sets)
        self.status = snap.get('status', self.status)

        prev_log_count = snap.get('play_log_count', len(self.play_by_play or []))
        current_logs = list(self.play_by_play or [])
        if len(current_logs) > prev_log_count:
            self.play_by_play = current_logs[:prev_log_count]

        self.play_by_play_snapshots = snapshots
        return True

    def reset_batter_count(self):
        """Resets balls, strikes, and courtesy foul according to league rules."""
        if self.season and self.season.league and self.season.league.softball_count_1_1_start:
            self.balls = 1
            self.strikes = 1
        else:
            self.balls = 0
            self.strikes = 0
        self.courtesy_foul_used = False

    def check_mercy_rule(self):
        """Returns dict with 'triggered': True/False, 'diff': int, 'leading_team': Team, 'message': str if satisfied."""
        if not self.season or not self.season.league:
            return {'triggered': False}
        league = self.season.league

        if self.game_type != 'regular' and not league.enforce_mercy_rule_in_playoffs:
            return {'triggered': False}

        diff = abs(self.team1_score - self.team2_score)
        if diff == 0:
            return {'triggered': False}
        leading_team = self.team1 if self.team1_score > self.team2_score else self.team2

        if league.mercy_rule_tier1_runs and league.mercy_rule_tier1_inning:
            if self.current_inning >= league.mercy_rule_tier1_inning and diff >= league.mercy_rule_tier1_runs:
                return {
                    'triggered': True,
                    'diff': diff,
                    'leading_team': leading_team,
                    'tier': 1,
                    'message': f"Mercy Rule Triggered: {leading_team.name} leads by {diff} runs after {self.current_inning} innings (Threshold: {league.mercy_rule_tier1_runs} runs after {league.mercy_rule_tier1_inning} inn)."
                }
        if league.mercy_rule_tier2_runs and league.mercy_rule_tier2_inning:
            if self.current_inning >= league.mercy_rule_tier2_inning and diff >= league.mercy_rule_tier2_runs:
                return {
                    'triggered': True,
                    'diff': diff,
                    'leading_team': leading_team,
                    'tier': 2,
                    'message': f"Mercy Rule Triggered: {leading_team.name} leads by {diff} runs after {self.current_inning} innings (Threshold: {league.mercy_rule_tier2_runs} runs after {league.mercy_rule_tier2_inning} inn)."
                }
        if league.mercy_rule_tier3_runs and league.mercy_rule_tier3_inning:
            if self.current_inning >= league.mercy_rule_tier3_inning and diff >= league.mercy_rule_tier3_runs:
                return {
                    'triggered': True,
                    'diff': diff,
                    'leading_team': leading_team,
                    'tier': 3,
                    'message': f"Mercy Rule Triggered: {leading_team.name} leads by {diff} runs after {self.current_inning} innings (Threshold: {league.mercy_rule_tier3_runs} runs after {league.mercy_rule_tier3_inning} inn)."
                }
        return {'triggered': False}


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

        if next_entry.is_automatic_out:
            self.outs += 1
            self.log_play(f"[AUTOMATIC OUT] Spot #{next_entry.batting_order} assessed 1 automatic out (short-handed lineup).")
            if self.outs >= 3:
                from leagues.services import scoring_engine
                scoring_engine.handle_side_retired(self, reason=f"3 outs (Auto-Out at Spot #{next_entry.batting_order})")
                return None
            else:
                return self.advance_to_next_batter()

        self.current_batter = next_entry.player
        self.reset_batter_count()
        return self.current_batter

    def peek_on_deck_batter(self):
        """Return the player who is on deck (up next after current_batter) for the batting team."""
        team = self.batting_team
        active_entries = self.get_active_lineup(team)
        if not active_entries:
            return None
        idx = (self.team1_batter_index if team == self.team1 else self.team2_batter_index) % len(active_entries)
        entry = active_entries[idx]
        if entry.is_automatic_out:
            return None
        return entry.player

    def decrement_disciplinary_suspensions(self):
        """When an official game is completed, decrement game-count suspensions for players on both teams."""
        if not self.season or not self.season.league:
            return
        league = self.season.league
        team_ids = [self.team1_id, self.team2_id]
        from leagues.models.discipline import PlayerDisciplinaryRecord
        active_records = PlayerDisciplinaryRecord.objects.filter(
            league=league,
            status='active',
            penalty_type='game_count',
            team_id__in=team_ids
        )
        for record in active_records:
            record.record_game_served()

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

    @property
    def has_assigned_official(self):
        return self.official_assignments.filter(status__in=['assigned', 'confirmed']).exists()

    def get_assigned_official_user_ids(self):
        return set(self.official_assignments.filter(status__in=['assigned', 'confirmed']).values_list('official_id', flat=True))

    def is_scorer_locked(self, user):
        """
        Returns True if another user currently holds an active, unexpired lock.
        Commissioners and assigned officials can override regular coach locks.
        """
        if not user or not user.is_authenticated:
            return True
        if not self.active_scorer_id or not self.active_scorer_expires_at:
            return False
        if self.active_scorer_expires_at <= timezone.now():
            return False
        if self.active_scorer_id == user.id:
            return False

        # Overall commissioner or league admin can override
        if user.is_overall_commissioner or (self.season and self.season.league and user.can_manage_league(self.season.league)):
            return False

        # If user is a certified referee or assigned official and active_scorer is not an official, official can override
        assigned_ids = self.get_assigned_official_user_ids()
        is_user_official = (user.id in assigned_ids) or (user.role == 'referee')
        is_active_official = (
            (self.active_scorer_id in assigned_ids) or
            (self.active_scorer and self.active_scorer.role == 'referee') or
            (self.active_scorer and self.active_scorer.is_overall_commissioner)
        )
        if is_user_official and not is_active_official:
            return False

        return True

    def acquire_scorer_lock(self, user):
        """Grants scoring lock to user for 2 minutes from now."""
        self.active_scorer = user
        self.active_scorer_expires_at = timezone.now() + timezone.timedelta(minutes=2)

    def log_score_event(self, user, action: str, details: str):
        entry = {
            'timestamp': timezone.now().isoformat(),
            'user_id': user.id if user and user.is_authenticated else None,
            'user_name': user.display_name if user and user.is_authenticated else 'System',
            'role': user.get_role_display() if user and user.is_authenticated else 'System',
            'action': action,
            'details': details,
            'team1_score': self.team1_score,
            'team2_score': self.team2_score,
            'status': self.status,
        }
        logs = list(self.score_audit_log or [])
        logs.append(entry)
        self.score_audit_log = logs

    def submit_score(self, user, t1_score=None, t2_score=None):
        """
        Handles score submission:
        - If user is certified referee, assigned official, or commissioner: immediately marks 'completed' & 'score_confirmed=True'.
        - If user is coach without assigned official: marks 'pending_confirmation'.
        """
        if t1_score is not None:
            self.team1_score = int(t1_score)
        if t2_score is not None:
            self.team2_score = int(t2_score)

        now = timezone.now()
        self.score_submitted_by = user
        self.score_submitted_at = now

        assigned_ids = self.get_assigned_official_user_ids()
        is_official = (
            user.id in assigned_ids
            or user.role == 'referee'
            or user.is_overall_commissioner
            or (self.season and self.season.league and user.can_manage_league(self.season.league))
        )

        if is_official:
            self.status = 'completed'
            self.score_confirmed = True
            self.score_confirmed_by = user
            self.log_score_event(
                user, 'official_finalized',
                f"Official score verified by {user.display_name}: {self.team1.name} {self.team1_score} - {self.team2_score} {self.team2.name}"
            )
        else:
            self.status = 'pending_confirmation'
            self.score_confirmed = False
            self.score_confirmed_by = None
            self.log_score_event(
                user, 'coach_submitted',
                f"Reported by {user.display_name}: {self.team1.name} {self.team1_score} - {self.team2_score} {self.team2.name} (Awaiting opponent confirmation)"
            )

    def confirm_score(self, user):
        """Opposing coach or commissioner confirms the pending score."""
        self.status = 'completed'
        self.score_confirmed = True
        self.score_confirmed_by = user
        self.log_score_event(
            user, 'score_confirmed',
            f"Score confirmed by {user.display_name}: {self.team1.name} {self.team1_score} - {self.team2_score} {self.team2.name}"
        )
        self.save(update_fields=['status', 'score_confirmed', 'score_confirmed_by', 'score_audit_log'])

    def dispute_score(self, user, dispute_notes: str = None, opposing_t1_score=None, opposing_t2_score=None, notes: str = None):
        """Opposing coach disputes the reported score."""
        final_notes = dispute_notes or notes or "Opposing coach contested the submitted score."
        self.status = 'disputed'
        self.score_dispute_notes = final_notes
        details = f"Disputed by {user.display_name}. Reason: {final_notes}"
        if opposing_t1_score is not None and opposing_t2_score is not None:
            details += f" (Claims score was {opposing_t1_score} - {opposing_t2_score})"
        self.log_score_event(user, 'score_disputed', details)
        self.save(update_fields=['status', 'score_dispute_notes', 'score_audit_log'])

    @classmethod
    def auto_finalize_stale_pending_games(cls, hours=48):
        """Auto-confirms games waiting on opponent confirmation past the review window."""
        with transaction.atomic():
            cutoff = timezone.now() - timezone.timedelta(hours=hours)
            stale_games = cls.objects.select_for_update().filter(
                status='pending_confirmation',
                score_submitted_at__lte=cutoff
            )
        count = 0
        for game in stale_games:
            game.status = 'completed'
            game.score_confirmed = True
            game.log_score_event(None, 'auto_finalized', f"Score auto-confirmed after {hours}h opponent review window without dispute.")
            game.save(update_fields=['status', 'score_confirmed', 'score_audit_log'])
            count += 1
        return count

    @transaction.atomic
    def record_forfeit(self, forfeiting_team=None, recording_user=None, winning_team=None, notes=""):

        """Standardizes 1-tap forfeit scoring and finalization by sport."""

        if winning_team and not forfeiting_team:

            forfeiting_team = self.team2 if (winning_team.id if hasattr(winning_team, 'id') else winning_team) == self.team1_id else self.team1

        elif forfeiting_team and not winning_team:

            winning_team = self.team2 if (forfeiting_team.id if hasattr(forfeiting_team, 'id') else forfeiting_team) == self.team1_id else self.team1



        sport = (self.season.league.sport if self.season and self.season.league else '').lower()

        scores_by_sport = {

            'softball': 7,

            'baseball': 7,

            'basketball': 15,

            'soccer': 2,

            'volleyball': 2,

            'flag_football': 14,

        }

        win_score = scores_by_sport.get(sport, 1)



        if forfeiting_team == self.team1:

            self.team1_score = 0

            self.team2_score = win_score

            non_forfeiting_name = self.team2.name

        else:

            self.team1_score = win_score

            self.team2_score = 0

            non_forfeiting_name = self.team1.name



        self.is_forfeit = True

        self.forfeit_winner = winning_team

        self.status = 'completed'

        self.score_confirmed = True

        self.score_confirmed_by = recording_user

        self.score_submitted_by = recording_user

        self.score_submitted_at = timezone.now()

        if notes:

            self.notes = f"{self.notes}\n[FORFEIT] {notes}".strip()

        user_name = recording_user.display_name if recording_user else "Scorekeeper"

        self.log_score_event(

            recording_user,

            'forfeit_recorded',

            f"Forfeit recorded by {user_name}. {forfeiting_team.name if forfeiting_team else 'Opponent'} forfeited to {non_forfeiting_name} ({self.team1_score}-{self.team2_score})."

        )

        self.log_play(f"[FORFEIT] {non_forfeiting_name} awarded forfeit victory ({self.team1_score}-{self.team2_score}).")

        self.save()

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


