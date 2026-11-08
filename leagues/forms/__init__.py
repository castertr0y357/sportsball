"""
Leagues forms package modularized by domain.
Re-exports all form classes for seamless backward compatibility.
"""

from .league_forms import LeagueForm, SeasonForm, ScheduleGeneratorForm, VenueRelocationForm
from .team_forms import TeamForm, SeasonRegistrationForm
from .game_forms import GameForm, GameScoreForm, ScoreDisputeForm, ScoreResolutionForm, ForfeitForm
from .discipline_forms import DisciplinaryActionForm, IncidentReportForm, SportsmanshipRatingForm

__all__ = [
    'LeagueForm',
    'SeasonForm',
    'ScheduleGeneratorForm',
    'VenueRelocationForm',
    'TeamForm',
    'SeasonRegistrationForm',
    'GameForm',
    'GameScoreForm',
    'ScoreDisputeForm',
    'ScoreResolutionForm',
    'ForfeitForm',
    'DisciplinaryActionForm',
    'IncidentReportForm',
    'SportsmanshipRatingForm',
]
