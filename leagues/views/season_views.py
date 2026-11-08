"""
Views for Season management, standings, calendar feeds, and weather rainouts.
"""

from __future__ import annotations
import datetime
from datetime import timedelta
from typing import Any
from django.contrib import messages
from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import ListView, CreateView, DetailView, View
from leagues.models import League, Season, Game
from leagues.forms import SeasonForm
from leagues.views.mixins import LeagueAdminRequiredMixin, SeasonAdminRequiredMixin
from leagues.services.calendar_feed import generate_ics_feed


class SeasonListView(ListView):
    """Lists all seasons within a specific league."""
    model = Season
    template_name = 'leagues/season_list.html'
    context_object_name = 'seasons'

    def get_queryset(self):
        self.league = get_object_or_404(League, id=self.kwargs['league_id'])
        return Season.objects.filter(league=self.league).prefetch_related('teams', 'games')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['league'] = self.league
        return context


class SeasonCreateView(LeagueAdminRequiredMixin, CreateView):
    """Establishes a new season within a league."""
    model = Season
    form_class = SeasonForm
    template_name = 'leagues/create_season.html'

    def form_valid(self, form):
        league = self.get_league()
        season = form.save(commit=False)
        season.league = league
        season.save()
        # Inherit officials from league master pool
        if league.master_officials_pool.exists():
            season.officials_pool.add(*league.master_officials_pool.all())
        messages.success(self.request, f"Season '{season.name}' created successfully.")
        return redirect('season_list', league_id=league.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['league'] = self.get_league()
        return context


class SeasonDetailView(DetailView):
    """Comprehensive season overview showing standings, schedule, playoffs, and registrations."""
    model = Season
    pk_url_kwarg = 'season_id'
    template_name = 'leagues/season_detail.html'
    context_object_name = 'season'

    def get_queryset(self):
        return Season.objects.select_related('league')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        season = self.object
        standings = season.get_standings()
        games = season.games.select_related('team1', 'team2').all()
        regular_games = [g for g in games if g.game_type == 'regular']
        playoff_games = [g for g in games if g.game_type != 'regular']
        registrations = season.registrations.select_related('player', 'preferred_team').all()
        user_registration = None
        can_manage_league = False
        today = timezone.localdate()
        today_games_count = season.games.filter(date__date=today, status='scheduled').count()

        if self.request.user.is_authenticated:
            user_registration = registrations.filter(player=self.request.user).first()
            can_manage_league = self.request.user.can_manage_league(season.league)

        context.update({
            'league': season.league,
            'standings': standings,
            'regular_games': regular_games,
            'playoff_games': playoff_games,
            'registrations': registrations,
            'user_registration': user_registration,
            'can_manage_league': can_manage_league,
            'today': today,
            'today_games_count': today_games_count,
        })
        return context


class SeasonCalendarIcsView(View):
    """Subscribable iCalendar feed (.ics) for all games in a season."""

    def get(self, request, season_id: int):
        season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
        games = season.games.select_related('team1', 'team2', 'season__league').order_by('date')
        calendar_title = f"{season.league.name} - {season.name}"
        filename = f"season_{season.id}_calendar.ics"
        ics_body = generate_ics_feed(games, calendar_title)
        response = HttpResponse(ics_body, content_type='text/calendar; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class RainoutTodayGamesView(SeasonAdminRequiredMixin, View):
    """1-Click mass weather postponement or makeup-week rollover for all scheduled games today."""

    def post(self, request, season_id: int):
        return self._handle_rainout(request)

    def get(self, request, season_id: int):
        return self._handle_rainout(request)

    def _handle_rainout(self, request):
        season = self.get_season()
        target_date_str = request.GET.get('date') or request.POST.get('date')
        if target_date_str:
            try:
                target_date = datetime.datetime.strptime(target_date_str, '%Y-%m-%d').date()
            except ValueError:
                target_date = timezone.localdate()
        else:
            target_date = timezone.localdate()

        games_today = list(season.games.filter(date__date=target_date, status='scheduled'))
        if not games_today:
            messages.warning(request, f"No scheduled games found on {target_date.strftime('%B %d, %Y')} to postpone.")
            return redirect('season_detail', season_id=season.id)

        action = request.POST.get('action') or request.GET.get('action') or 'reschedule_makeup'
        max_week = season.games.filter(game_type='regular').aggregate(Max('week_number'))['week_number__max'] or 1
        makeup_week = max_week + 1
        count = len(games_today)

        for g in games_today:
            orig_date_str = g.date.strftime('%a %b %d')
            if action == 'postpone_only':
                g.status = 'postponed'
                g.notes = f"Postponed / Weather rainout on {orig_date_str}. {g.notes or ''}".strip()
                g.save(update_fields=['status', 'notes'])
            else:
                weeks_ahead = max(1, makeup_week - (g.week_number or 1))
                g.date = g.date + timedelta(days=7 * weeks_ahead)
                g.week_number = makeup_week
                g.status = 'scheduled'
                g.notes = f"Rescheduled from rainout on {orig_date_str}. {g.notes or ''}".strip()
                g.save(update_fields=['date', 'week_number', 'status', 'notes'])

        if action == 'postpone_only':
            messages.warning(request, f"🌧️ Weather Rainout: {count} game(s) on {target_date.strftime('%b %d')} have been marked Postponed.")
        else:
            messages.success(request, f"🌧️ Weather Rainout: {count} game(s) from {target_date.strftime('%b %d')} have been moved to Makeup Week {makeup_week}!")

        return redirect('season_detail', season_id=season.id)


class RescheduleRainoutsView(SeasonAdminRequiredMixin, View):
    """Batch reschedule assistant for rained out / postponed games."""

    def get(self, request, season_id: int):
        season = self.get_season()
        rainout_games = season.games.filter(status__in=['rainout', 'postponed']).select_related('team1', 'team2').order_by('date')
        return render(request, 'leagues/reschedule_rainouts.html', {
            'season': season,
            'rainout_games': rainout_games,
        })

    def post(self, request, season_id: int):
        season = self.get_season()
        rainout_games = season.games.filter(status__in=['rainout', 'postponed']).select_related('team1', 'team2').order_by('date')
        game_ids = request.POST.getlist('selected_games')
        target_date_str = request.POST.get('target_date')
        target_time_str = request.POST.get('target_time', '18:00')
        interval_minutes = int(request.POST.get('interval_minutes', 60))

        if not target_date_str:
            messages.error(request, "Please choose a target makeup date.")
            return redirect('reschedule_rainouts', season_id=season.id)

        try:
            target_date = datetime.datetime.strptime(target_date_str, '%Y-%m-%d').date()
            time_parts = [int(p) for p in target_time_str.split(':')]
            start_time = datetime.time(time_parts[0], time_parts[1])
        except Exception:
            messages.error(request, "Invalid makeup date or time format.")
            return redirect('reschedule_rainouts', season_id=season.id)

        target_dt = datetime.datetime.combine(target_date, start_time)
        target_tz_dt = timezone.make_aware(target_dt, timezone.get_current_timezone())

        moved_count = 0
        current_slot = target_tz_dt
        for gid in game_ids:
            g = rainout_games.filter(id=gid).first()
            if g:
                g.date = current_slot
                g.status = 'scheduled'
                g.notes = (f"{g.notes or ''}\nRescheduled makeup for {current_slot.strftime('%b %d @ %I:%M %p')}").strip()
                g.save(update_fields=['date', 'status', 'notes'])
                current_slot += timedelta(minutes=interval_minutes)
                moved_count += 1

        messages.success(request, f"✓ Successfully rescheduled {moved_count} game(s) to {target_date.strftime('%A, %b %d, %Y')}.")
        return redirect('season_detail', season_id=season.id)
