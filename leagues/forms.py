from django import forms
from .models import League, Season, Team, SeasonRegistration, Game


class LeagueForm(forms.ModelForm):
    class Meta:
        model = League
        fields = ['name', 'sport', 'description', 'rules', 'discord_webhook_url', 'admin']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'rules': forms.Textarea(attrs={'rows': 4}),
        }


class SeasonForm(forms.ModelForm):
    class Meta:
        model = Season
        fields = [
            'name', 'start_date', 'end_date', 'current',
            'registration_open', 'registration_fee', 'max_roster_size',
            'discord_webhook_url', 'venmo_handle', 'cashapp_handle', 'paypal_link',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['name', 'church', 'captain', 'team_color', 'players', 'dues_paid']
        widgets = {
            'players': forms.CheckboxSelectMultiple(),
        }


class SeasonRegistrationForm(forms.ModelForm):
    class Meta:
        model = SeasonRegistration
        fields = ['preferred_team', 'is_free_agent', 'waiver_agreed', 'notes']
        labels = {
            'waiver_agreed': 'I agree to the season liability waiver and Christian sportsmanship code',
            'is_free_agent': 'Register me as a Free Agent (place me on any church team needing players)',
        }

    def __init__(self, *args, season=None, **kwargs):
        super().__init__(*args, **kwargs)
        if season is not None:
            self.fields['preferred_team'].queryset = Team.objects.filter(season=season)


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
            qs = Team.objects.filter(season=season)
            self.fields['team1'].queryset = qs
            self.fields['team2'].queryset = qs


class GameScoreForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = ['team1_score', 'team2_score', 'status', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class ScheduleGeneratorForm(forms.Form):
    start_datetime = forms.DateTimeField(
        label="First Game Date & Time",
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text="Start time for Week 1 games"
    )
    location = forms.CharField(
        max_length=200,
        initial="Fellowship Hall Gym - Court A",
        label="Default Venue / Field / Court"
    )
    double_round_robin = forms.BooleanField(
        required=False,
        initial=False,
        label="Double Round-Robin (each team plays every other team twice: home & away)"
    )
    clear_existing_scheduled = forms.BooleanField(
        required=False,
        initial=False,
        label="Replace existing unplayed regular-season scheduled games"
    )
