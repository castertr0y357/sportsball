"""Forms for church team creation and season player registrations."""
from __future__ import annotations
from django import forms
from leagues.models import Team, SeasonRegistration
from core.models import Church
from users.models import CustomUser
from django.db.models import Q


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


