"""GameLineupEntry and GameRSVP models managing batting orders, defensive rotations, and attendance."""
from __future__ import annotations
from django.db import models
from django.conf import settings


class GameLineupEntry(models.Model):
    game = models.ForeignKey('Game', on_delete=models.CASCADE, related_name='lineup_entries')
    team = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='game_lineups')
    player = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='lineup_appearances')
    batting_order = models.PositiveIntegerField(default=1)
    is_present = models.BooleanField(default=True, help_text="Checked in / present at the ballpark today")
    field_position = models.CharField(max_length=120, blank=True, help_text="e.g., SS / P or primary position")
    position_rotations = models.JSONField(default=dict, blank=True, help_text="Inning or period rotations (e.g. {'1': 'SS', '2': 'P'})")
    is_emergency_sub = models.BooleanField(default=False, help_text="Emergency pickup player to avoid forfeit")
    sub_consented_by_opponent = models.BooleanField(default=False, help_text="Opposing coach consented to this emergency sub at game time")

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
    game = models.ForeignKey('Game', on_delete=models.CASCADE, related_name='rsvps')
    player = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='game_rsvps')
    response = models.CharField(max_length=10, choices=RESPONSE_CHOICES, default='yes')
    notes = models.CharField(max_length=150, blank=True, help_text="e.g. Running 10 mins late")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = [('game', 'player')]

    def __str__(self):
        return f"{self.player.display_name} -> {self.get_response_display()} ({self.game})"


