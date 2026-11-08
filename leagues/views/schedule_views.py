"""
Views for Match Scheduling, Schedule Generation, Matrix Grid, and Playoff Tournament Brackets.
"""

from __future__ import annotations
import datetime
from datetime import timedelta
from typing import Any
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import View, TemplateView
from leagues.models import Season, Game
from leagues.forms import GameForm, ScheduleGeneratorForm
from leagues.views.mixins import SeasonAdminRequiredMixin
from leagues.services.scheduler import ScheduleGeneratorService
from leagues.services import playoff_engine


class CreateGameView(SeasonAdminRequiredMixin, View):
    """Manually schedules a single matchup with double-booking collision detection."""

    def get(self, request, season_id: int):
        season = self.get_season()
        default_dt = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
        form = GameForm(
            season=season,
            initial={'date': default_dt.strftime('%Y-%m-%dT%H:%M'), 'location': 'Fellowship Hall Gym'}
        )
        return render(request, 'leagues/create_game.html', {'form': form, 'season': season})

    def post(self, request, season_id: int):
        season = self.get_season()
        form = GameForm(request.POST, season=season)
        if form.is_valid():
            game = form.save(commit=False)
            game.season = season
            game.save()
            messages.success(request, f"Game scheduled: {game.team1.name} vs {game.team2.name}.")
            return redirect('season_detail', season_id=season.id)

        return render(request, 'leagues/create_game.html', {'form': form, 'season': season})


class GenerateScheduleView(SeasonAdminRequiredMixin, View):
    """Automated round-robin scheduler respecting church service blackout hours."""

    def get(self, request, season_id: int):
        season = self.get_season()
        teams = list(season.teams.all())
        if len(teams) < 2:
            messages.error(request, "At least 2 teams are required in the season to generate a schedule.")
            return redirect('season_detail', season_id=season.id)

        form = ScheduleGeneratorForm()
        return render(request, 'leagues/generate_schedule.html', {
            'form': form,
            'season': season,
            'team_count': len(teams),
            'preview_games': None,
        })

    def post(self, request, season_id: int):
        season = self.get_season()
        teams = list(season.teams.all())
        if len(teams) < 2:
            messages.error(request, "At least 2 teams are required in the season to generate a schedule.")
            return redirect('season_detail', season_id=season.id)

        form = ScheduleGeneratorForm(request.POST)
        preview_games = None

        if form.is_valid():
            start_date = form.cleaned_data['start_date']
            game_days = form.cleaned_data['parsed_game_days']
            time_slots = form.cleaned_data['parsed_time_slots']
            venues = form.cleaned_data['parsed_venues']
            blackout_dates = form.cleaned_data['parsed_blackout_dates']
            protect_wednesdays = form.cleaned_data.get('protect_wednesdays', True)
            protect_sunday_mornings = form.cleaned_data.get('protect_sunday_mornings', True)
            double_rr = form.cleaned_data.get('double_round_robin', False)
            add_buffer = form.cleaned_data.get('add_weather_buffer', True)
            clear_existing = form.cleaned_data.get('clear_existing_scheduled', True)

            service = ScheduleGeneratorService(
                season=season,
                start_date=start_date,
                game_days=game_days,
                time_slots=time_slots,
                venues=venues,
                blackout_dates=blackout_dates,
                protect_wednesdays=protect_wednesdays,
                protect_sunday_mornings=protect_sunday_mornings,
                double_round_robin=double_rr,
                add_weather_buffer=add_buffer,
            )

            action = request.POST.get('action', 'generate')
            if action == 'preview':
                preview_games = service.plan_schedule()
                messages.info(request, f"Generated draft schedule preview with {len(preview_games)} matchups. Review below and click 'Save & Publish Schedule' to confirm.")
            else:
                created_count = service.execute_and_save(clear_existing_scheduled=clear_existing)
                messages.success(request, f"Success! {created_count} regular-season games generated and scheduled.")
                return redirect('schedule_grid', season_id=season.id)

        return render(request, 'leagues/generate_schedule.html', {
            'form': form,
            'season': season,
            'team_count': len(teams),
            'preview_games': preview_games,
        })


class PlayoffBracketView(View):
    """Visual elimination tournament bracket displaying seeds, matchups, and champion."""

    def get(self, request, season_id: int):
        season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
        standings = season.get_standings()
        semifinals = season.games.filter(game_type='playoff_sf').select_related('team1', 'team2')
        finals = season.games.filter(game_type='playoff_final').select_related('team1', 'team2')
        consolations = season.games.filter(game_type='consolation').select_related('team1', 'team2')
        champion = None
        for f in finals:
            if f.status == 'completed' and f.winner:
                champion = f.winner

        return render(request, 'leagues/playoff_bracket.html', {
            'season': season,
            'standings': standings,
            'semifinals': semifinals,
            'finals': finals,
            'consolations': consolations,
            'champion': champion,
        })


class GeneratePlayoffsView(SeasonAdminRequiredMixin, View):
    """Triggers automated playoff tournament generation from regular season standings."""

    def post(self, request, season_id: int):
        season = self.get_season()
        success, msg = playoff_engine.generate_playoff_bracket(season)
        if success:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect('playoff_bracket', season_id=season.id)

    def get(self, request, season_id: int):
        return redirect('playoff_bracket', season_id=season_id)


class AdvancePlayoffsToFinalView(SeasonAdminRequiredMixin, View):
    """Advances semifinal winners into the Championship Final and sets consolation match."""

    def post(self, request, season_id: int):
        season = self.get_season()
        success, msg = playoff_engine.advance_semifinals_to_final(season)
        if success:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect('playoff_bracket', season_id=season.id)

    def get(self, request, season_id: int):
        return redirect('playoff_bracket', season_id=season_id)


class ScheduleGridView(View):
    """Weekly master matrix grid with drag/swap capabilities and quick rainout triggers."""

    def get(self, request, season_id: int):
        season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
        can_manage = request.user.is_authenticated and request.user.can_manage_league(season.league)
        games = season.games.select_related('team1', 'team2').order_by('week_number', 'date', 'location')

        weeks_dict = {}
        for g in games:
            w = g.week_number or 1
            if w not in weeks_dict:
                weeks_dict[w] = []
            weeks_dict[w].append(g)

        weeks = sorted(weeks_dict.items(), key=lambda x: x[0])
        today = timezone.localdate()
        today_games_count = season.games.filter(date__date=today, status='scheduled').count()

        return render(request, 'leagues/schedule_grid.html', {
            'season': season,
            'weeks': weeks,
            'can_manage': can_manage,
            'today': today,
            'today_games_count': today_games_count,
        })


class SwapGameSlotsView(SeasonAdminRequiredMixin, View):
    """Swaps date, time, court, and week numbers between two games."""

    def post(self, request, season_id: int):
        season = self.get_season()
        game1_id = request.POST.get('game1_id')
        game2_id = request.POST.get('game2_id')

        g1 = get_object_or_404(Game, id=game1_id, season=season)
        g2 = get_object_or_404(Game, id=game2_id, season=season)

        g1.date, g2.date = g2.date, g1.date
        g1.location, g2.location = g2.location, g1.location
        g1.week_number, g2.week_number = g2.week_number, g1.week_number

        g1.save(update_fields=['date', 'location', 'week_number'])
        g2.save(update_fields=['date', 'location', 'week_number'])

        messages.success(request, f"Successfully swapped slots between '{g1.team1.name} vs {g1.team2.name}' and '{g2.team1.name} vs {g2.team2.name}'.")
        return redirect('schedule_grid', season_id=season.id)
