from django.contrib import admin
from .models import League, Season, Team, SeasonRegistration, Game, GameLineupEntry


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ('name', 'sport', 'admin', 'created_at')
    search_fields = ('name', 'admin__username')
    list_filter = ('sport', 'created_at')


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ('league', 'name', 'start_date', 'end_date', 'current', 'registration_open', 'registration_fee')
    list_filter = ('league', 'current', 'registration_open')
    search_fields = ('league__name', 'name')


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'league', 'season', 'church', 'captain', 'player_count', 'dues_paid')
    list_filter = ('league', 'season', 'church', 'dues_paid')
    search_fields = ('name', 'league__name', 'church__name')
    filter_horizontal = ('players',)

    @admin.display(description='Players')
    def player_count(self, obj):
        return obj.players.count()


@admin.register(SeasonRegistration)
class SeasonRegistrationAdmin(admin.ModelAdmin):
    list_display = ('player', 'season', 'preferred_team', 'is_free_agent', 'status', 'waiver_agreed', 'dues_paid', 'created_at')
    list_filter = ('season', 'status', 'is_free_agent', 'waiver_agreed', 'dues_paid')
    search_fields = ('player__username', 'player__email', 'season__name')


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('season', 'week_number', 'game_type', 'team1', 'team1_score', 'team2', 'team2_score', 'current_inning', 'inning_half', 'outs', 'status')
    list_filter = ('season', 'status', 'game_type')
    search_fields = ('team1__name', 'team2__name', 'location')


@admin.register(GameLineupEntry)
class GameLineupEntryAdmin(admin.ModelAdmin):
    list_display = ('game', 'team', 'batting_order', 'player', 'field_position', 'is_present')
    list_filter = ('team', 'is_present')
    search_fields = ('player__username', 'player__first_name', 'player__last_name', 'team__name')
