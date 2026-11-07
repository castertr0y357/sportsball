import datetime
from leagues.services.scheduler import parse_time_str
from django import forms
from django.db.models import Q
from .models import League, Season, Team, SeasonRegistration, Game
from core.models import Church
from users.models import CustomUser


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
        fields = ['name', 'church', 'captain', 'team_color']
        widgets = {
            'team_color': forms.TextInput(attrs={'placeholder': 'e.g. Royal Blue'}),
        }

    def __init__(self, *args, user=None, target_church=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not user.is_overall_commissioner:
            # Church commissioner can only register for their church
            effective_church = target_church or user.managed_churches.first() or user.church
            if effective_church:
                self.fields['church'].queryset = Church.objects.filter(id=effective_church.id)
                self.fields['church'].initial = effective_church
                self.fields['church'].empty_label = None
                self.fields['captain'].queryset = CustomUser.objects.filter(
                    Q(church=effective_church) | Q(role__in=['coach', 'player', 'church_admin'])
                ).distinct()
        else:
            self.fields['captain'].queryset = CustomUser.objects.filter(
                role__in=['coach', 'player', 'church_admin', 'admin']
            ).distinct()


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


class ScheduleGeneratorForm(forms.Form):
    start_date = forms.DateField(
        label="League Start Date",
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}),
        initial=datetime.date.today,
        required=False,
        help_text="Date for Week 1 games (e.g. your opening game day)"
    )
    # Legacy field compatibility
    start_datetime = forms.DateTimeField(
        required=False,
        widget=forms.HiddenInput()
    )
    game_days = forms.MultipleChoiceField(
        label="Game Days of the Week",
        choices=GAME_DAY_CHOICES,
        initial=['1', '3'],  # Tuesday & Thursday default
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-checkbox-group'}),
        required=False,
        help_text="Days of the week when games will be hosted"
    )
    time_slots = forms.CharField(
        label="Daily Game Time Slots",
        initial="18:30, 19:45",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input'}),
        help_text="Comma-separated game start times (e.g. 18:30, 19:45 or 9:00 AM, 10:15 AM)"
    )
    venues = forms.CharField(
        label="Courts / Fields / Venues",
        initial="Court 1\nCourt 2",
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-input'}),
        help_text="List venues or courts (one per line). Multiple venues enable parallel simultaneous games."
    )
    # Legacy field compatibility
    location = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.HiddenInput()
    )
    blackout_dates = forms.CharField(
        label="Blackout Dates (Skip)",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'YYYY-MM-DD, YYYY-MM-DD'}),
        help_text="Comma-separated dates to skip (e.g. revival weeks, holiday weekends)"
    )
    protect_wednesdays = forms.BooleanField(
        label="Protect Wednesday Evenings",
        initial=True,
        required=False,
        help_text="Never schedule games at or after 5:00 PM on Wednesdays (worship/prayer/choir services)."
    )
    protect_sunday_mornings = forms.BooleanField(
        label="Protect Sunday Mornings",
        initial=True,
        required=False,
        help_text="Never schedule games before 1:00 PM on Sundays (church worship services)."
    )
    double_round_robin = forms.BooleanField(
        label="Double Round Robin (Home & Away)",
        initial=False,
        required=False,
        help_text="Each team plays every other team twice (home & away)."
    )
    add_weather_buffer = forms.BooleanField(
        label="Reserve Weather Buffer Week",
        initial=True,
        required=False,
        help_text="Reserves an extra makeup week before playoffs for rained out or postponed games."
    )
    clear_existing_scheduled = forms.BooleanField(
        label="Clear Existing Scheduled Games",
        initial=True,
        required=False,
        help_text="Delete previously generated regular-season games that have not yet been played."
    )

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        start_dt = cleaned_data.get('start_datetime')
        if not start_date and start_dt:
            start_date = start_dt.date()
            cleaned_data['start_date'] = start_date
        elif not start_date:
            cleaned_data['start_date'] = datetime.date.today()

        venues_raw = cleaned_data.get('venues', '').strip()
        location_raw = cleaned_data.get('location', '').strip()
        if not venues_raw and location_raw:
            venues_list = [location_raw]
        elif venues_raw:
            venues_list = [v.strip() for v in venues_raw.splitlines() if v.strip()]
        else:
            venues_list = ["Court 1", "Court 2"]
        cleaned_data['parsed_venues'] = venues_list

        raw_days = cleaned_data.get('game_days') or ['1', '3']
        cleaned_data['parsed_game_days'] = [int(d) for d in raw_days if str(d).isdigit()] or [1, 3]

        raw_slots = cleaned_data.get('time_slots', '')
        slots = []
        if raw_slots:
            for part in raw_slots.split(','):
                part = part.strip()
                if part:
                    slots.append(parse_time_str(part))
        cleaned_data['parsed_time_slots'] = slots or [datetime.time(18, 30)]

        raw_blackouts = cleaned_data.get('blackout_dates', '')
        blackouts = set()
        if raw_blackouts:
            for part in raw_blackouts.split(','):
                part = part.strip()
                if not part:
                    continue
                for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d'):
                    try:
                        blackouts.add(datetime.datetime.strptime(part, fmt).date())
                        break
                    except ValueError:
                        pass
        cleaned_data['parsed_blackout_dates'] = blackouts

        return cleaned_data
