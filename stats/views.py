"""
Views for player and team statistical leaderboards across seasons and categories.
"""

from __future__ import annotations
from django.views.generic import View
from django.shortcuts import render, get_object_or_404
from django.db.models import Sum, Avg, Count, Max
from .models import PlayerGameStat, SPORT_DEFAULT_CATEGORIES
from leagues.models import Season, League


class LeaderboardView(View):
    """Player statistical leaderboard by season and category."""

    def get(self, request):
        season_id = request.GET.get('season')
        category = request.GET.get('category', '')

        seasons = Season.objects.select_related('league').all()
        selected_season = None
        if season_id:
            selected_season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
        else:
            selected_season = seasons.filter(current=True).first() or seasons.first()

        stats_qs = PlayerGameStat.objects.select_related('player__church', 'team', 'game__season')
        if selected_season:
            stats_qs = stats_qs.filter(game__season=selected_season)

        available_categories = list(
            stats_qs.values_list('category', flat=True).distinct().order_by('category')
        )
        if not available_categories and selected_season:
            sport = selected_season.league.sport
            available_categories = [name for name, _abbr in SPORT_DEFAULT_CATEGORIES.get(sport, SPORT_DEFAULT_CATEGORIES['other'])]

        if not category and available_categories:
            category = available_categories[0]

        leaders = []
        if category:
            leaders = (
                stats_qs.filter(category=category)
                .values(
                    'player__id',
                    'player__username',
                    'player__first_name',
                    'player__last_name',
                    'player__church__name',
                    'team__id',
                    'team__name',
                )
                .annotate(
                    total_value=Sum('value'),
                    games_played=Count('game', distinct=True),
                    avg_value=Avg('value'),
                    high_value=Max('value'),
                )
                .order_by('-total_value', '-avg_value')[:25]
            )

        return render(request, 'stats/leaderboard.html', {
            'seasons': seasons,
            'selected_season': selected_season,
            'available_categories': available_categories,
            'selected_category': category,
            'leaders': leaders,
        })


leaderboard = LeaderboardView.as_view()
