"""Forms for recording disciplinary actions, incident reports, and sportsmanship ratings."""
from __future__ import annotations
from django import forms
from leagues.models import PlayerDisciplinaryRecord


class DisciplinaryActionForm(forms.Form):
    player_id = forms.IntegerField(required=True)
    team_id = forms.IntegerField(required=False)
    penalty_type = forms.ChoiceField(
        choices=[
            ('game_count', 'Game Count Suspension'),
            ('date_bound', 'Date-Bound Suspension'),
            ('permanent_expulsion', 'Permanent Expulsion'),
        ],
        initial='game_count'
    )
    games_suspended_total = forms.IntegerField(initial=1, min_value=1, required=False)
    suspended_until = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    dues_forfeited = forms.BooleanField(required=False)
    reason = forms.CharField(widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Provide specific rationale and scripture/code references'}))


class IncidentReportForm(forms.Form):
    player_id = forms.IntegerField(required=True)
    incident_type = forms.ChoiceField(
        choices=[
            ('misconduct', 'Player Misconduct'),
            ('dispute', 'Disputed Call / Unsportsmanlike Conduct'),
            ('equipment', 'Equipment / Safety Violation'),
            ('other', 'Other Incident'),
        ],
        initial='misconduct'
    )
    description = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}))
    is_ejection = forms.BooleanField(required=False)


class SportsmanshipRatingForm(forms.Form):
    rated_team_id = forms.IntegerField(required=True)
    score = forms.IntegerField(min_value=1, max_value=5, initial=5)
    respect_for_officials = forms.IntegerField(min_value=1, max_value=5, initial=5)
    bench_conduct = forms.IntegerField(min_value=1, max_value=5, initial=5)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))


