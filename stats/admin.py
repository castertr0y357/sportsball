from django.contrib import admin
from .models import StatCategory, PlayerGameStat


@admin.register(StatCategory)
class StatCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'abbreviation', 'sport', 'description')
    list_filter = ('sport',)
    search_fields = ('name', 'abbreviation')


@admin.register(PlayerGameStat)
class PlayerGameStatAdmin(admin.ModelAdmin):
    list_display = ('player', 'team', 'game', 'category', 'value')
    list_filter = ('category', 'team', 'game__season')
    search_fields = ('player__username', 'category', 'team__name')
