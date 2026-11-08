"""
Domain venue and field management service.
Handles weather status updates, field closures, atomic game relocations,
conflict resolution, and notification dispatching.
"""

from __future__ import annotations
from datetime import date
from typing import Optional
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from leagues.models import Game, LeagueVenue, League
from core.services.notifications import send_discord_notification


def update_venue_condition(
    venue: LeagueVenue,
    status: str,
    status_note: str = "",
    updated_by = None
) -> None:
    """Updates playability status for a venue and notifies league if closed or in conflict."""
    venue.status = status
    venue.status_note = status_note
    venue.status_updated_by = updated_by
    venue.save(update_fields=['status', 'status_note', 'status_updated_at', 'status_updated_by'])

    league = venue.league
    if status in ('closed', 'conflict') and league.discord_webhook_url:
        send_discord_notification(
            league.discord_webhook_url,
            f"📢 Field Alert ({league.name}): {venue.name} is {venue.get_status_display().upper()}. {status_note}"
        )


@transaction.atomic
def relocate_or_postpone_games(
    venue: LeagueVenue,
    action_type: str,
    new_venue: Optional[LeagueVenue] = None,
    target_date: Optional[date] = None,
    reason: str = ""
) -> tuple[int, str]:
    """
    1-Click atomic game relocator / postponer.
    Returns (games_count: int, message: str).
    """
    league = venue.league
    games_qs = Game.objects.filter(
        season__league=league,
        status='scheduled'
    ).filter(Q(venue=venue) | Q(location__icontains=venue.name))

    if target_date:
        games_qs = games_qs.filter(date__date=target_date)

    games_list = list(games_qs)
    if not games_list:
        return 0, f"No scheduled games found at {venue.name} for the specified date."

    count = len(games_list)

    if action_type == 'relocate':
        if not new_venue:
            raise ValueError("Target venue is required for relocation.")
        for g in games_list:
            g.venue = new_venue
            g.location = new_venue.name
            g.save(update_fields=['venue', 'location'])

        if league.discord_webhook_url:
            send_discord_notification(
                league.discord_webhook_url,
                f"🚨 Field Relocation Alert: {count} game(s) originally at {venue.name} moved to {new_venue.name}. Reason: {reason or 'Field conditions'}"
            )
        return count, f"⚡ Successfully relocated {count} game(s) from {venue.name} to {new_venue.name}."

    else:  # postpone
        for g in games_list:
            g.status = 'postponed'
            g.notes = f"{g.notes}\n[POSTPONED]: {reason or 'Field closed due to weather/conflict'}".strip()
            g.save(update_fields=['status', 'notes'])

        if league.discord_webhook_url:
            send_discord_notification(
                league.discord_webhook_url,
                f"🌧️ Weather Postponement: All games at {venue.name} postponed. Reason: {reason or 'Unplayable conditions'}"
            )
        return count, f"🌧️ Postponed {count} game(s) at {venue.name}."
