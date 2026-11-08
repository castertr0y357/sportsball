"""
Domain playoff and tournament engine.
Handles playoff bracket generation from regular season standings,
semifinal seeding (e.g. 1 vs 4, 2 vs 3), consolation matches, and final advancement.
"""

from __future__ import annotations
from datetime import timedelta
from typing import Any
from django.utils import timezone
from leagues.models import Game, Season, Team


def generate_playoff_bracket(season: Season) -> tuple[bool, str]:
    """
    Generates playoff bracket games based on current regular season standings.
    Returns (success: bool, message: str).
    """
    standings = season.get_standings()
    if len(standings) < 2:
        return False, "Need at least 2 teams to generate playoffs."

    # Clear existing unscheduled/scheduled playoff games
    season.games.filter(
        game_type__in=['playoff_qf', 'playoff_sf', 'playoff_final', 'consolation'],
        status='scheduled'
    ).delete()

    base_dt = timezone.now().replace(hour=19, minute=0, second=0, microsecond=0) + timedelta(days=7)

    if len(standings) >= 4:
        seed1 = standings[0]['team']
        seed2 = standings[1]['team']
        seed3 = standings[2]['team']
        seed4 = standings[3]['team']

        Game.objects.create(
            season=season,
            team1=seed1,
            team2=seed4,
            playoff_seed1=1,
            playoff_seed2=4,
            date=base_dt,
            location="Main Sanctuary Gym - Court 1",
            game_type='playoff_sf',
            week_number=99,
            notes="Semifinal #1: #1 Seed vs #4 Seed",
        )
        Game.objects.create(
            season=season,
            team1=seed2,
            team2=seed3,
            playoff_seed1=2,
            playoff_seed2=3,
            date=base_dt + timedelta(hours=1, minutes=15),
            location="Main Sanctuary Gym - Court 1",
            game_type='playoff_sf',
            week_number=99,
            notes="Semifinal #2: #2 Seed vs #3 Seed",
        )
        return True, "Top 4 Playoff Semifinal bracket generated from current standings!"
    else:
        seed1 = standings[0]['team']
        seed2 = standings[1]['team']
        Game.objects.create(
            season=season,
            team1=seed1,
            team2=seed2,
            playoff_seed1=1,
            playoff_seed2=2,
            date=base_dt,
            location="Main Sanctuary Gym - Championship Court",
            game_type='playoff_final',
            week_number=100,
            notes="Championship Final: #1 Seed vs #2 Seed",
        )
        return True, "Championship Final matchup generated (#1 vs #2)!"


def advance_semifinals_to_final(season: Season) -> tuple[bool, str]:
    """
    Advances completed semifinals to Championship Final and 3rd Place Consolation match.
    Returns (success: bool, message: str).
    """
    semis = list(season.games.filter(game_type='playoff_sf', status='completed').order_by('id'))
    if len(semis) < 2 or not semis[0].winner or not semis[1].winner:
        return False, "Both Semifinal games must be completed with a winner before generating the Championship Final."

    w1 = semis[0].winner
    w2 = semis[1].winner
    l1 = semis[0].team2 if semis[0].winner == semis[0].team1 else semis[0].team1
    l2 = semis[1].team2 if semis[1].winner == semis[1].team1 else semis[1].team1

    final_dt = semis[-1].date + timedelta(days=3)
    season.games.filter(game_type__in=['playoff_final', 'consolation'], status='scheduled').delete()

    Game.objects.create(
        season=season,
        team1=l1,
        team2=l2,
        date=final_dt,
        location="Main Sanctuary Gym - Fellowship Court",
        game_type='consolation',
        week_number=100,
        notes="3rd Place Fellowship Match",
    )
    Game.objects.create(
        season=season,
        team1=w1,
        team2=w2,
        date=final_dt + timedelta(hours=1, minutes=30),
        location="Main Sanctuary Gym - Championship Court",
        game_type='playoff_final',
        week_number=100,
        notes="League Championship Final",
    )
    return True, f"Championship Final ({w1.name} vs {w2.name}) and 3rd Place Match scheduled!"
