"""PlayerDisciplinaryRecord and GameSportsmanshipRating models enforcing Christian conduct."""
from __future__ import annotations
from django.db import models
from django.conf import settings
from django.utils import timezone


class PlayerDisciplinaryRecord(models.Model):
    PENALTY_TYPE_CHOICES = [
        ('game_count', 'Game Count Suspension'),
        ('date_bound', 'Date-Bound Suspension'),
        ('permanent_expulsion', 'Permanent Expulsion / League Ban'),
        ('formal_warning', 'Official Written Warning'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active Penalty'),
        ('served', 'Completed / Reinstated'),
        ('appealed', 'Under Committee Appeal'),
        ('rescinded', 'Rescinded by Commissioner'),
    ]

    player = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='disciplinary_records')
    league = models.ForeignKey('League', on_delete=models.CASCADE, related_name='disciplinary_records')
    team = models.ForeignKey('Team', on_delete=models.SET_NULL, null=True, blank=True, related_name='disciplinary_records')
    game = models.ForeignKey('Game', on_delete=models.SET_NULL, null=True, blank=True, related_name='disciplinary_incidents')

    penalty_type = models.CharField(max_length=30, choices=PENALTY_TYPE_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', db_index=True)

    games_suspended_total = models.PositiveIntegerField(default=0)
    games_served = models.PositiveIntegerField(default=0)
    suspended_until = models.DateTimeField(null=True, blank=True)
    dues_forfeited = models.BooleanField(default=False)

    reason = models.TextField(help_text="Explanation of incident or by-law violation")
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='issued_penalties')
    issued_at = models.DateTimeField(auto_now_add=True)
    reinstated_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-issued_at']

    def is_currently_active(self):
        if self.status != 'active':
            return False
        if self.penalty_type == 'permanent_expulsion':
            return True
        if self.penalty_type == 'date_bound' and self.suspended_until:
            return timezone.now() < self.suspended_until
        if self.penalty_type == 'game_count':
            return self.games_served < self.games_suspended_total
        return False

    def remaining_games(self):
        if self.penalty_type != 'game_count':
            return 0
        return max(0, self.games_suspended_total - self.games_served)

    def record_game_served(self):
        """Increment served games. If reached total, automatically reinstate!"""
        if self.penalty_type == 'game_count' and self.status == 'active':
            self.games_served += 1
            if self.games_served >= self.games_suspended_total:
                self.status = 'served'
                self.reinstated_at = timezone.now()
                self.resolution_notes = f"{self.resolution_notes}\n[AUTO-REINSTATED]: Served full {self.games_suspended_total} game suspension.".strip()
            self.save(update_fields=['games_served', 'status', 'reinstated_at', 'resolution_notes'])

    def __str__(self):
        return f"{self.player.display_name} - {self.get_penalty_type_display()} ({self.get_status_display()})"




class GameSportsmanshipRating(models.Model):
    EVALUATOR_ROLE_CHOICES = [
        ('official', 'Umpire / Referee'),
        ('coach', 'Opposing Coach'),
        ('commissioner', 'League Commissioner / Field Marshal'),
    ]

    game = models.ForeignKey('Game', on_delete=models.CASCADE, related_name='sportsmanship_ratings')
    evaluator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='submitted_sportsmanship_ratings')
    evaluator_role = models.CharField(max_length=20, choices=EVALUATOR_ROLE_CHOICES)
    rated_team = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='received_sportsmanship_ratings')

    score = models.PositiveIntegerField(default=5, help_text="1 to 5 stars overall fellowship score")
    respect_for_officials = models.PositiveIntegerField(default=5, help_text="1 to 5 stars conduct towards officials")
    bench_conduct = models.PositiveIntegerField(default=5, help_text="1 to 5 stars sideline/bench decorum")
    notes = models.TextField(blank=True, help_text="Specific observations or praise")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('game', 'evaluator', 'rated_team')]

    def __str__(self):
        return f"{self.rated_team.name} rated {self.score}★ by {self.evaluator.display_name} ({self.get_evaluator_role_display()})"
