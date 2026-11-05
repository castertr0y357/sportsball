from django import forms
from .models import PlayerGameStat, StatCategory


class PlayerGameStatForm(forms.ModelForm):
    class Meta:
        model = PlayerGameStat
        fields = ['player', 'team', 'category', 'value']

    def __init__(self, *args, game=None, **kwargs):
        super().__init__(*args, **kwargs)
        if game is not None:
            from users.models import CustomUser
            team_ids = [game.team1_id, game.team2_id]
            players_qs = CustomUser.objects.filter(teams__id__in=team_ids).distinct()
            if not players_qs.exists():
                players_qs = CustomUser.objects.all()
            self.fields['player'].queryset = players_qs
            self.fields['team'].queryset = game.season.teams.filter(id__in=team_ids) if game.season_id else None


class StatCategoryForm(forms.ModelForm):
    class Meta:
        model = StatCategory
        fields = ['sport', 'name', 'abbreviation', 'description']
