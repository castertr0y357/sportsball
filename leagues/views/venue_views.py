"""
Views for Venue Playability Condition updates and 1-Click Atomic Game Relocations.
"""

from __future__ import annotations
import datetime
from typing import Any
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import View
from leagues.models import LeagueVenue
from leagues.services import venue_service


class UpdateVenueStatusView(LoginRequiredMixin, View):
    """Updates venue/field playability status (open, caution, closed, conflict, maintenance)."""

    def post(self, request, venue_id: int):
        venue = get_object_or_404(LeagueVenue.objects.select_related('league'), id=venue_id)
        league = venue.league
        if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
            messages.error(request, "Permission denied to update venue status.")
            return redirect('manage_league_pools', league_id=league.id)

        status = request.POST.get('status', 'open')
        status_note = request.POST.get('status_note', '').strip()

        venue_service.update_venue_condition(
            venue=venue,
            status=status,
            status_note=status_note,
            updated_by=request.user
        )
        messages.success(request, f"Updated condition status for {venue.name}: {venue.get_status_display()}.")
        return redirect(request.META.get('HTTP_REFERER') or 'home')


class RelocateVenueGamesView(LoginRequiredMixin, View):
    """1-Click atomic game relocator: moves scheduled games from one field to another or postpones them."""

    def post(self, request, venue_id: int):
        venue = get_object_or_404(LeagueVenue.objects.select_related('league'), id=venue_id)
        league = venue.league
        if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
            messages.error(request, "Permission denied.")
            return redirect('manage_league_pools', league_id=league.id)

        action_type = request.POST.get('action_type', 'relocate')
        target_date_str = request.POST.get('target_date')
        new_venue_id = request.POST.get('new_venue_id')
        reason = request.POST.get('reason', '').strip()

        target_date = None
        if target_date_str:
            try:
                target_date = datetime.datetime.strptime(target_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        new_venue = None
        if action_type == 'relocate':
            new_venue = get_object_or_404(LeagueVenue, id=new_venue_id, league=league)

        count, msg = venue_service.relocate_or_postpone_games(
            venue=venue,
            action_type=action_type,
            new_venue=new_venue,
            target_date=target_date,
            reason=reason
        )

        if count == 0:
            messages.warning(request, msg)
        else:
            messages.success(request, msg)

        return redirect('manage_league_pools', league_id=league.id)
