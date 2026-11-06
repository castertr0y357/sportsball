from django.urls import path
from . import views

urlpatterns = [
    path('', views.league_list, name='league_list'),
    path('create/', views.create_league, name='create_league'),
    path('<int:league_id>/seasons/', views.season_list, name='season_list'),
    path('<int:league_id>/seasons/create/', views.create_season, name='create_season'),
    path('seasons/<int:season_id>/', views.season_detail, name='season_detail'),
    path('seasons/<int:season_id>/teams/', views.team_list, name='team_list'),
    path('seasons/<int:season_id>/teams/create/', views.create_team, name='create_team'),
    path('seasons/<int:season_id>/register/', views.register_for_season, name='register_for_season'),
    path('seasons/<int:season_id>/games/create/', views.create_game, name='create_game'),
    path('seasons/<int:season_id>/schedule/generate/', views.generate_schedule, name='generate_schedule'),
    path('seasons/<int:season_id>/playoffs/', views.playoff_bracket, name='playoff_bracket'),
    path('seasons/<int:season_id>/playoffs/generate/', views.generate_playoffs, name='generate_playoffs'),
    path('seasons/<int:season_id>/playoffs/advance/', views.advance_playoffs_to_final, name='advance_playoffs_to_final'),
    path('registrations/<int:reg_id>/assign/', views.assign_registration, name='assign_registration'),
    path('teams/<int:team_id>/', views.team_detail, name='team_detail'),
    path('teams/<int:team_id>/join/', views.join_team, name='join_team'),
    path('teams/join/<str:invite_code>/', views.join_team_by_invite, name='join_team_invite'),
    path('games/<int:game_id>/', views.game_detail, name='game_detail'),
    path('games/<int:game_id>/score/', views.record_game_score, name='record_game_score'),
    path('games/<int:game_id>/stats/add/', views.add_game_stat, name='add_game_stat'),
    # Simplified GameChanger: Single-Operator Dugout Console & Public GameCast
    path('games/<int:game_id>/console/', views.dugout_console, name='dugout_console'),
    path('games/<int:game_id>/console/action/', views.dugout_action, name='dugout_action'),
    path('games/<int:game_id>/console/sync/', views.dugout_batch_sync, name='dugout_batch_sync'),
    path('games/<int:game_id>/gamecast/', views.gamecast, name='gamecast'),
    path('games/<int:game_id>/live-state/', views.game_live_state, name='game_live_state'),
    # Zero-consequences Practice & Training Sandbox
    path('practice-sandbox/', views.practice_sandbox, name='practice_sandbox'),
]
