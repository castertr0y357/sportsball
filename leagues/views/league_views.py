"""
Views for League management, master venue pools, and master officials pools.
"""

from __future__ import annotations
from typing import Any
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, View
from leagues.models import League, LeagueVenue, Season
from leagues.forms import LeagueForm
from leagues.views.mixins import LeagueAdminRequiredMixin
from users.models import CustomUser


class LeagueListView(ListView):
    """Public list of active sports leagues with associated seasons."""
    model = League
    template_name = 'leagues/league_list.html'
    context_object_name = 'leagues'

    def get_queryset(self):
        return League.objects.select_related('admin').prefetch_related('seasons').all()


class LeagueCreateView(LoginRequiredMixin, CreateView):
    """Allows league commissioners to configure and establish a new league."""
    model = League
    form_class = LeagueForm
    template_name = 'leagues/create_league.html'
    success_url = reverse_lazy('league_list')

    def dispatch(self, request, *args, **kwargs):
        if not (request.user.is_overall_commissioner or request.user.is_league_admin):
            messages.error(request, "You don't have permission to create leagues.")
            return redirect('league_list')
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial['admin'] = self.request.user
        return initial

    def form_valid(self, form):
        league = form.save()
        messages.success(self.request, f"League '{league.name}' created successfully.")
        return redirect('league_list')


class LeaguePoolsView(LeagueAdminRequiredMixin, View):
    """Commissioner dashboard for managing master officials and venues across all seasons."""

    def get(self, request, league_id: int):
        league = self.get_league()
        seasons = league.seasons.all()
        venues = league.venues.all().order_by('name')
        officials = league.master_officials_pool.all().order_by('first_name', 'last_name')
        available_users = CustomUser.objects.filter(is_active=True).exclude(
            id__in=officials.values_list('id', flat=True)
        ).order_by('first_name', 'last_name')[:40]

        return render(request, 'leagues/manage_pools.html', {
            'league': league,
            'seasons': seasons,
            'venues': venues,
            'officials': officials,
            'available_users': available_users,
            'available_officials': available_users,
        })


class AddLeagueVenueView(LeagueAdminRequiredMixin, View):
    """Adds a new home court or field to the league master venue pool."""

    def post(self, request, league_id: int):
        league = self.get_league()
        name = request.POST.get('name', '').strip()
        address = request.POST.get('address', '').strip()
        notes = request.POST.get('notes', '').strip()
        if name:
            LeagueVenue.objects.create(
                league=league,
                name=name,
                address=address,
                notes=notes,
                is_active=True
            )
            messages.success(request, f"✓ Added venue '{name}' to league master pool.")
        else:
            messages.error(request, "Venue name cannot be blank.")
        return redirect('manage_league_pools', league_id=league.id)


class ToggleLeagueVenueView(LeagueAdminRequiredMixin, View):
    """Enables or disables a venue for automatic schedule generation."""

    def post(self, request, league_id: int, venue_id: int):
        league = self.get_league()
        venue = get_object_or_404(LeagueVenue, id=venue_id, league=league)
        venue.is_active = not venue.is_active
        venue.save(update_fields=['is_active'])
        status_str = "active" if venue.is_active else "inactive"
        messages.success(request, f"Venue '{venue.name}' is now marked as {status_str}.")
        return redirect('manage_league_pools', league_id=league.id)


class DeleteLeagueVenueView(LeagueAdminRequiredMixin, View):
    """Removes a venue from the league pool."""

    def post(self, request, league_id: int, venue_id: int):
        league = self.get_league()
        venue = get_object_or_404(LeagueVenue, id=venue_id, league=league)
        v_name = venue.name
        venue.delete()
        messages.info(request, f"Deleted venue '{v_name}' from league pool.")
        return redirect('manage_league_pools', league_id=league.id)


class AddLeagueOfficialView(LeagueAdminRequiredMixin, View):
    """Adds a referee or umpire to the league master pool."""

    def post(self, request, league_id: int):
        league = self.get_league()
        user_id = request.POST.get('user_id')
        user = get_object_or_404(CustomUser, id=user_id)
        league.master_officials_pool.add(user)
        messages.success(request, f"✓ Added {user.display_name} to league master officials pool.")
        return redirect('manage_league_pools', league_id=league.id)


class RemoveLeagueOfficialView(LeagueAdminRequiredMixin, View):
    """Removes an official from the league master pool."""

    def post(self, request, league_id: int, user_id: int):
        league = self.get_league()
        user = get_object_or_404(CustomUser, id=user_id)
        league.master_officials_pool.remove(user)
        messages.info(request, f"Removed {user.display_name} from league master officials pool.")
        return redirect('manage_league_pools', league_id=league.id)
