"""
Reusable Class-Based View (CBV) mixins for authorization, JSON API handling,
and entity resolution.
"""

from __future__ import annotations
from typing import Any, Optional
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from leagues.models import League, Season, Team, Game


class JsonResponseMixin:
    """Standardizes JSON responses across Dugout and scoring AJAX endpoints."""

    def json_success(self, data: Optional[dict[str, Any]] = None, message: str = "") -> JsonResponse:
        payload = {'status': 'ok'}
        if message:
            payload['message'] = message
        if data:
            payload.update(data)
        return JsonResponse(payload)

    def json_error(self, message: str, status: int = 400, errors: Optional[dict[str, Any]] = None) -> JsonResponse:
        payload = {'status': 'error', 'error': message}
        if errors:
            payload['errors'] = errors
        return JsonResponse(payload, status=status)


class LeagueAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Verifies that the user has administrative privileges for the target League."""

    league_url_kwarg = 'league_id'

    def get_league(self) -> League:
        if hasattr(self, 'league') and self.league is not None:
            return self.league
        league_id = self.kwargs.get(self.league_url_kwarg)
        self.league = get_object_or_404(League, id=league_id)
        return self.league

    def test_func(self) -> bool:
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_overall_commissioner or user.is_league_admin:
            return True
        league = self.get_league()
        return user.can_manage_league(league)

    def handle_no_permission(self) -> HttpResponseRedirect:
        messages.error(self.request, "You don't have permission to manage this league.")
        return redirect('league_list')


class SeasonAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Verifies that the user has administrative privileges for the target Season or parent League."""

    season_url_kwarg = 'season_id'

    def get_season(self) -> Season:
        if hasattr(self, 'season') and self.season is not None:
            return self.season
        season_id = self.kwargs.get(self.season_url_kwarg)
        self.season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
        return self.season

    def test_func(self) -> bool:
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_overall_commissioner or user.is_league_admin:
            return True
        season = self.get_season()
        return user.can_manage_league(season.league)

    def handle_no_permission(self) -> HttpResponseRedirect:
        messages.error(self.request, "You don't have permission to manage this season.")
        season_id = self.kwargs.get(self.season_url_kwarg)
        if season_id:
            return redirect('season_detail', season_id=season_id)
        return redirect('league_list')


class TeamCoachRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Verifies that the user is the Team Captain, Coach, or League Administrator."""

    team_url_kwarg = 'team_id'

    def get_team(self) -> Team:
        if hasattr(self, 'team') and self.team is not None:
            return self.team
        team_id = self.kwargs.get(self.team_url_kwarg)
        self.team = get_object_or_404(Team.objects.select_related('league', 'captain'), id=team_id)
        return self.team

    def test_func(self) -> bool:
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_overall_commissioner or user.is_league_admin:
            return True
        team = self.get_team()
        return (team.captain_id == user.id) or user.can_manage_league(team.league)

    def handle_no_permission(self) -> HttpResponseRedirect:
        messages.error(self.request, "Only the team captain or league commissioner can perform this action.")
        team_id = self.kwargs.get(self.team_url_kwarg)
        if team_id:
            return redirect('team_detail', team_id=team_id)
        return redirect('league_list')


class ScorekeeperAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Verifies that the user can score or manage dugout actions for the Game."""

    game_url_kwarg = 'game_id'

    def get_game(self) -> Game:
        if hasattr(self, 'game') and self.game is not None:
            return self.game
        game_id = self.kwargs.get(self.game_url_kwarg)
        self.game = get_object_or_404(
            Game.objects.select_related(
                'season__league', 'team1__church', 'team2__church',
                'current_batter', 'active_scorer'
            ),
            id=game_id
        )
        return self.game

    def test_func(self) -> bool:
        user = self.request.user
        if not user.is_authenticated:
            return False
        game = self.get_game()
        return user.can_score_game(game)

    def handle_no_permission(self) -> Any:
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'json' in self.request.content_type:
            return JsonResponse({'status': 'error', 'error': 'Permission denied to score this match.'}, status=403)
        messages.error(self.request, "Only assigned referees, participating team captains, or league commissioners can open the Dugout Operator Console.")
        game_id = self.kwargs.get(self.game_url_kwarg)
        if game_id:
            return redirect('game_detail', game_id=game_id)
        return redirect('league_list')
