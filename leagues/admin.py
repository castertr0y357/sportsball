from django.contrib import admin
from .models import (
    League, Season, Team, SeasonRegistration, Game, GameLineupEntry,
    LeagueVenue, PlayerDisciplinaryRecord, GameSportsmanshipRating
)


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ('name', 'sport', 'admin', 'allow_emergency_subs', 'allow_minors', 'sportsmanship_good_threshold', 'created_at')
    search_fields = ('name', 'admin__username')
    list_filter = ('sport', 'allow_emergency_subs', 'allow_minors', 'created_at')


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
    list_display = ('game', 'team', 'batting_order', 'player', 'field_position', 'is_present', 'is_emergency_sub')
    list_filter = ('team', 'is_present', 'is_emergency_sub')
    search_fields = ('player__username', 'player__first_name', 'player__last_name', 'team__name')


@admin.register(LeagueVenue)
class LeagueVenueAdmin(admin.ModelAdmin):
    list_display = ('name', 'league', 'status', 'status_note', 'status_updated_at', 'is_active')
    list_filter = ('league', 'status', 'is_active')
    search_fields = ('name', 'league__name', 'address')


@admin.register(PlayerDisciplinaryRecord)
class PlayerDisciplinaryRecordAdmin(admin.ModelAdmin):
    list_display = ('player', 'league', 'team', 'penalty_type', 'status', 'games_suspended_total', 'games_served', 'suspended_until', 'issued_at')
    list_filter = ('league', 'penalty_type', 'status')
    search_fields = ('player__username', 'player__first_name', 'player__last_name', 'reason')


@admin.register(GameSportsmanshipRating)
class GameSportsmanshipRatingAdmin(admin.ModelAdmin):
    list_display = ('game', 'rated_team', 'evaluator', 'evaluator_role', 'score', 'respect_for_officials', 'bench_conduct', 'created_at')
    list_filter = ('evaluator_role', 'score')
    search_fields = ('rated_team__name', 'evaluator__username', 'game__team1__name', 'game__team2__name')
