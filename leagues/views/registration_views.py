"""
Views for Player Season Registration, Free Agent placement, and Roster Importing.
"""

from __future__ import annotations
from typing import Any
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import View
from leagues.models import Season, SeasonRegistration, Team
from leagues.forms import SeasonRegistrationForm
from leagues.views.mixins import SeasonAdminRequiredMixin


class RegisterForSeasonView(LoginRequiredMixin, View):
    """Submits player registration (preferred team or free agent) and executes digital liability waiver."""

    def get(self, request, season_id: int):
        season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
        existing = SeasonRegistration.objects.filter(season=season, player=request.user).first()
        form = SeasonRegistrationForm(
            instance=existing,
            season=season,
            initial={'waiver_agreed': request.user.waiver_signed}
        )
        return render(request, 'leagues/season_register.html', {'form': form, 'season': season})

    def post(self, request, season_id: int):
        season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
        existing = SeasonRegistration.objects.filter(season=season, player=request.user).first()
        form = SeasonRegistrationForm(request.POST, instance=existing, season=season)
        if form.is_valid():
            reg = form.save(commit=False)
            reg.season = season
            reg.player = request.user
            if reg.is_free_agent or not reg.preferred_team:
                reg.is_free_agent = True
                request.user.is_free_agent = True
                request.user.save(update_fields=['is_free_agent'])
            if reg.waiver_agreed and not request.user.waiver_signed:
                request.user.sign_waiver(request.user.display_name)
            reg.save()
            messages.success(request, f"Registration submitted for {season.name}!")
            return redirect('season_detail', season_id=season.id)

        return render(request, 'leagues/season_register.html', {'form': form, 'season': season})


class AssignRegistrationView(LoginRequiredMixin, View):
    """Assigns free agents or preferred registrations to a team roster and updates dues."""

    def post(self, request, reg_id: int):
        reg = get_object_or_404(
            SeasonRegistration.objects.select_related('season__league', 'player__church', 'preferred_team__church'),
            id=reg_id
        )
        user = request.user
        if not user.can_manage_teams:
            messages.error(request, "You do not have permission to manage registrations.")
            return redirect('season_detail', season_id=reg.season_id)

        team_id = request.POST.get('team_id')
        action = request.POST.get('action', 'approve')

        if action == 'toggle_dues':
            can_manage_dues = (
                user.is_overall_commissioner or
                user.can_manage_league(reg.season.league) or
                (reg.player.church and user.can_manage_church(reg.player.church))
            )
            if not can_manage_dues:
                messages.error(request, "Only Church or League Commissioners can update player dues status.")
                return redirect('season_detail', season_id=reg.season_id)

            reg.dues_paid = not reg.dues_paid
            reg.save(update_fields=['dues_paid'])
            messages.success(request, f"Updated dues status for {reg.player.display_name}.")

        elif action == 'approve':
            target_team = get_object_or_404(Team, id=team_id, season=reg.season) if team_id else reg.preferred_team
            if not target_team:
                messages.error(request, "Please select a team to assign this player to.")
                return redirect('season_detail', season_id=reg.season_id)

            can_assign_to_target = (
                user.is_overall_commissioner or
                user.can_manage_league(reg.season.league) or
                user.can_manage_church(target_team.church) or
                target_team.captain_id == user.id
            )
            if not can_assign_to_target:
                messages.error(request, f"You do not have permission to roster players to {target_team.name}.")
                return redirect('season_detail', season_id=reg.season_id)

            target_team.players.add(reg.player)
            reg.preferred_team = target_team
            reg.status = 'approved'
            reg.is_free_agent = False
            reg.save()
            reg.player.is_free_agent = False
            reg.player.save(update_fields=['is_free_agent'])
            messages.success(request, f"{reg.player.display_name} assigned to {target_team.name}!")

        return redirect('season_detail', season_id=reg.season_id)


class ImportSeasonTeamsView(SeasonAdminRequiredMixin, View):
    """Allows League Commissioner to 1-tap re-use / import teams from an earlier season."""

    def get(self, request, season_id: int):
        season = self.get_season()
        league = season.league
        other_seasons = league.seasons.exclude(id=season.id).order_by('-start_date')
        selected_source_id = request.GET.get('source_season_id')
        source_season = None
        source_teams = []

        if selected_source_id:
            source_season = get_object_or_404(Season, id=selected_source_id, league=league)
            source_teams = source_season.teams.all().select_related('church', 'captain')

        return render(request, 'leagues/import_teams.html', {
            'season': season,
            'league': league,
            'other_seasons': other_seasons,
            'source_season': source_season,
            'source_teams': source_teams,
        })

    def post(self, request, season_id: int):
        season = self.get_season()
        league = season.league
        selected_source_id = request.POST.get('source_season_id')
        source_season = get_object_or_404(Season, id=selected_source_id, league=league)

        team_ids = request.POST.getlist('selected_teams')
        if not team_ids:
            messages.warning(request, "No teams selected for import.")
            return redirect(f"{request.path}?source_season_id={selected_source_id}")

        existing_names = set(season.teams.values_list('name', flat=True))
        imported_count = 0
        for st in source_season.teams.filter(id__in=team_ids):
            if st.name not in existing_names:
                Team.objects.create(
                    name=st.name,
                    league=league,
                    season=season,
                    church=st.church,
                    captain=st.captain,
                    team_color=st.team_color,
                    dues_paid=False,
                    default_lineup=st.default_lineup,
                )
                existing_names.add(st.name)
                imported_count += 1

        messages.success(request, f"Successfully imported {imported_count} team(s) into {season.name}.")
        return redirect('season_detail', season_id=season_id)
