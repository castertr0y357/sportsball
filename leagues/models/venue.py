"""LeagueVenue model managing persistent home fields/courts and weather playability states."""
from __future__ import annotations
from django.db import models
from django.conf import settings


class LeagueVenue(models.Model):
    VENUE_STATUS_CHOICES = [
        ('open', 'Open & Playable'),
        ('caution', 'Caution / Wet Conditions'),
        ('closed', 'Closed / Unplayable (Weather)'),
        ('conflict', 'Conflict / Relocated'),
        ('maintenance', 'Facility Maintenance'),
    ]

    league = models.ForeignKey('League', on_delete=models.CASCADE, related_name='venues')
    name = models.CharField(max_length=150, help_text="Venue / Field / Court Name (e.g. Field #1, North Gym)")
    address = models.CharField(max_length=255, blank=True, help_text="Street address or location directions")
    notes = models.TextField(blank=True, help_text="Parking notes, gate codes, lighting switches")
    status = models.CharField(max_length=20, choices=VENUE_STATUS_CHOICES, default='open')
    status_note = models.CharField(max_length=255, blank=True, help_text="e.g. Infield standing water. Games moved to Turf Field 2.")
    status_updated_at = models.DateTimeField(auto_now=True)
    status_updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='venue_status_updates')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = [('league', 'name')]

    def __str__(self):
        return f"{self.name} ({self.league.name})"


