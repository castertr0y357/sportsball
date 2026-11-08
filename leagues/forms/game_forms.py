"""Forms for game scheduling, score reporting, forfeits, and dispute resolutions."""
from __future__ import annotations
from django import forms
from leagues.models import Game, Team


class GameForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = [
            'team1', 'team2', 'date', 'location',
            'game_type', 'week_number', 'status', 'notes',
        ]
        widgets = {
            'date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, season=None, **kwargs):
        super().__init__(*args, **kwargs)
        if season is not None:
            teams_qs = Team.objects.filter(season=season)
            self.fields['team1'].queryset = teams_qs
            self.fields['team2'].queryset = teams_qs

    def clean(self):
        cleaned_data = super().clean()
        date = cleaned_data.get('date')
        location = cleaned_data.get('location', '').strip()
        team1 = cleaned_data.get('team1')
        team2 = cleaned_data.get('team2')

        if team1 and team2 and team1 == team2:
            raise forms.ValidationError('A team cannot play against itself.')

        if date and location:
            from datetime import timedelta
            # Venue double-booking conflict check within 90-minute window
            start_window = date - timedelta(minutes=89)
            end_window = date + timedelta(minutes=89)
            conflicts = Game.objects.filter(
                location__iexact=location,
                date__gte=start_window,
                date__lte=end_window,
                status__in=['scheduled', 'in_progress']
            )
            if self.instance and self.instance.pk:
                conflicts = conflicts.exclude(pk=self.instance.pk)

            conflict = conflicts.first()
            if conflict:
                time_str = conflict.date.strftime('%b %d at %I:%M %p')
                raise forms.ValidationError(
                    f"Venue Conflict: '{conflict.team1.name} vs {conflict.team2.name}' is already scheduled at '{location}' on {time_str}."
                )
        return cleaned_data


class GameScoreForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = ['team1_score', 'team2_score', 'status', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


GAME_DAY_CHOICES = [
    ('0', 'Mon'),
    ('1', 'Tue'),
    ('2', 'Wed'),
    ('3', 'Thu'),
    ('4', 'Fri'),
    ('5', 'Sat'),
    ('6', 'Sun'),
]




class ScoreDisputeForm(forms.Form):
    notes = forms.CharField(widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Specify the score discrepancy, incorrect inning, or disputed call'}))


class ScoreResolutionForm(forms.Form):
    team1_score = forms.IntegerField(min_value=0)
    team2_score = forms.IntegerField(min_value=0)
    resolution_notes = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}))


class ForfeitForm(forms.Form):
    winner_id = forms.IntegerField(required=True)
    notes = forms.CharField(required=False, widget=forms.TextInput(attrs={'placeholder': 'e.g. Insufficient players at game time'}))
