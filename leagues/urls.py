"""
URL Configuration for the leagues app.
Routes are organized into logical domain groupings utilizing Class-Based Views (CBVs).
"""

from django.urls import path
from leagues.views import (
    # League & Master Pools
    LeagueListView,
    LeagueCreateView,
    LeaguePoolsView,
    AddLeagueVenueView,
    ToggleLeagueVenueView,
    DeleteLeagueVenueView,
    AddLeagueOfficialView,
    RemoveLeagueOfficialView,
    # Seasons & Weather
    SeasonListView,
    SeasonCreateView,
    SeasonDetailView,
    SeasonCalendarIcsView,
    RainoutTodayGamesView,
    RescheduleRainoutsView,
    # Teams & Rosters
    TeamListView,
    TeamCreateView,
    TeamDetailView,
    ManageRosterPlayerView,
    JoinTeamView,
    JoinTeamByInviteView,
    ToggleTeamDuesView,
    TeamCalendarIcsView,
    # Registration & Imports
    RegisterForSeasonView,
    AssignRegistrationView,
    ImportSeasonTeamsView,
    # Scheduling & Playoffs
    CreateGameView,
    GenerateScheduleView,
    PlayoffBracketView,
    GeneratePlayoffsView,
    AdvancePlayoffsToFinalView,
    ScheduleGridView,
    SwapGameSlotsView,
    # Officials & Umpires
    OfficialsHubView,
    RespondOfficialAssignmentView,
    ClaimOfficialAssignmentView,
    ToggleOfficialPaymentView,
    # Games, RSVPs & Lineups
    GameDetailView,
    RecordGameScoreView,
    AddGameStatView,
    GameRSVPView,
    GameLineupBuilderView,
    GameLineupPrintView,
    UserCalendarIcsView,
    # Dugout Console & Live GameCast
    DugoutConsoleView,
    DugoutActionView,
    DugoutBatchSyncView,
    GameLiveStateView,
    GamecastView,
    PracticeSandboxView,
    TakeOverDugoutScoringView,
    # Disputes & Forfeits
    ConfirmGameScoreView,
    DisputeGameScoreView,
    ResolveScoreDisputeView,
    BulkConfirmPendingScoresView,
    RecordGameForfeitView,
    # Venues & Mass Relocation
    UpdateVenueStatusView,
    RelocateVenueGamesView,
    # Discipline & Sportsmanship
    ManageDisciplinaryHubView,
    ReinstateDisciplinaryPenaltyView,
    ReportGameIncidentView,
    SubmitSportsmanshipRatingView,
    ManageSportsmanshipDashboardView,
)

urlpatterns = [
    # -------------------------------------------------------------------------
    # 1. League Management & Master Franchise Pools
    # -------------------------------------------------------------------------
    path('', LeagueListView.as_view(), name='league_list'),
    path('create/', LeagueCreateView.as_view(), name='create_league'),
    path('<int:league_id>/pools/', LeaguePoolsView.as_view(), name='manage_league_pools'),
    path('<int:league_id>/pools/venues/add/', AddLeagueVenueView.as_view(), name='add_league_venue'),
    path('<int:league_id>/pools/venues/<int:venue_id>/toggle/', ToggleLeagueVenueView.as_view(), name='toggle_league_venue'),
    path('<int:league_id>/pools/venues/<int:venue_id>/delete/', DeleteLeagueVenueView.as_view(), name='delete_league_venue'),
    path('<int:league_id>/pools/officials/add/', AddLeagueOfficialView.as_view(), name='add_league_official'),
    path('<int:league_id>/pools/officials/<int:user_id>/remove/', RemoveLeagueOfficialView.as_view(), name='remove_league_official'),

    # -------------------------------------------------------------------------
    # 2. Season Management, Calendar Sync & Rainout Rollover
    # -------------------------------------------------------------------------
    path('<int:league_id>/seasons/', SeasonListView.as_view(), name='season_list'),
    path('<int:league_id>/seasons/create/', SeasonCreateView.as_view(), name='create_season'),
    path('seasons/<int:season_id>/', SeasonDetailView.as_view(), name='season_detail'),
    path('seasons/<int:season_id>/calendar.ics', SeasonCalendarIcsView.as_view(), name='season_calendar_ics'),
    path('seasons/<int:season_id>/rainout-today/', RainoutTodayGamesView.as_view(), name='rainout_today_games'),
    path('seasons/<int:season_id>/reschedule-rainouts/', RescheduleRainoutsView.as_view(), name='reschedule_rainouts'),

    # -------------------------------------------------------------------------
    # 3. Team Management, Roster Editing & Invitations
    # -------------------------------------------------------------------------
    path('seasons/<int:season_id>/teams/', TeamListView.as_view(), name='team_list'),
    path('seasons/<int:season_id>/teams/create/', TeamCreateView.as_view(), name='create_team'),
    path('teams/<int:team_id>/', TeamDetailView.as_view(), name='team_detail'),
    path('teams/<int:team_id>/roster/manage/', ManageRosterPlayerView.as_view(), name='manage_roster_player'),
    path('teams/<int:team_id>/join/', JoinTeamView.as_view(), name='join_team'),
    path('teams/join/<str:invite_code>/', JoinTeamByInviteView.as_view(), name='join_team_invite'),
    path('teams/<int:team_id>/toggle-dues/', ToggleTeamDuesView.as_view(), name='toggle_team_dues'),
    path('teams/<int:team_id>/calendar.ics', TeamCalendarIcsView.as_view(), name='team_calendar_ics'),

    # -------------------------------------------------------------------------
    # 4. Player Registration & Team Imports
    # -------------------------------------------------------------------------
    path('seasons/<int:season_id>/register/', RegisterForSeasonView.as_view(), name='register_for_season'),
    path('registrations/<int:reg_id>/assign/', AssignRegistrationView.as_view(), name='assign_registration'),
    path('seasons/<int:season_id>/teams/import/', ImportSeasonTeamsView.as_view(), name='import_season_teams'),

    # -------------------------------------------------------------------------
    # 5. Scheduling, Grid Matrix & Playoff Brackets
    # -------------------------------------------------------------------------
    path('seasons/<int:season_id>/games/create/', CreateGameView.as_view(), name='create_game'),
    path('seasons/<int:season_id>/schedule/generate/', GenerateScheduleView.as_view(), name='generate_schedule'),
    path('seasons/<int:season_id>/schedule-grid/', ScheduleGridView.as_view(), name='schedule_grid'),
    path('seasons/<int:season_id>/schedule/swap/', SwapGameSlotsView.as_view(), name='swap_game_slots'),
    path('seasons/<int:season_id>/playoffs/', PlayoffBracketView.as_view(), name='playoff_bracket'),
    path('seasons/<int:season_id>/playoffs/generate/', GeneratePlayoffsView.as_view(), name='generate_playoffs'),
    path('seasons/<int:season_id>/playoffs/advance/', AdvancePlayoffsToFinalView.as_view(), name='advance_playoffs_to_final'),

    # -------------------------------------------------------------------------
    # 6. Officials Hub, Assignments & Fee Payments
    # -------------------------------------------------------------------------
    path('seasons/<int:season_id>/officials/', OfficialsHubView.as_view(), name='officials_hub'),
    path('officials/assignments/<int:assignment_id>/respond/', RespondOfficialAssignmentView.as_view(), name='respond_official_assignment'),
    path('officials/assignments/<int:assignment_id>/claim/', ClaimOfficialAssignmentView.as_view(), name='claim_official_assignment'),
    path('officials/assignments/<int:assignment_id>/toggle-payment/', ToggleOfficialPaymentView.as_view(), name='toggle_official_payment'),

    # -------------------------------------------------------------------------
    # 7. Games, Lineups, RSVPs & Stats
    # -------------------------------------------------------------------------
    path('games/<int:game_id>/', GameDetailView.as_view(), name='game_detail'),
    path('games/<int:game_id>/rsvp/', GameRSVPView.as_view(), name='game_rsvp'),
    path('games/<int:game_id>/lineup/<int:team_id>/', GameLineupBuilderView.as_view(), name='game_lineup_builder'),
    path('games/<int:game_id>/lineup/<int:team_id>/print/', GameLineupPrintView.as_view(), name='game_lineup_print'),
    path('games/<int:game_id>/score/', RecordGameScoreView.as_view(), name='record_game_score'),
    path('games/<int:game_id>/stats/add/', AddGameStatView.as_view(), name='add_game_stat'),
    path('calendar/my-games.ics', UserCalendarIcsView.as_view(), name='user_calendar_ics'),

    # -------------------------------------------------------------------------
    # 8. Live Dugout Console, GameCast & Practice Sandbox
    # -------------------------------------------------------------------------
    path('games/<int:game_id>/console/', DugoutConsoleView.as_view(), name='dugout_console'),
    path('games/<int:game_id>/console/action/', DugoutActionView.as_view(), name='dugout_action'),
    path('games/<int:game_id>/console/sync/', DugoutBatchSyncView.as_view(), name='dugout_batch_sync'),
    path('games/<int:game_id>/console/takeover/', TakeOverDugoutScoringView.as_view(), name='take_over_dugout_scoring'),
    path('games/<int:game_id>/live-state/', GameLiveStateView.as_view(), name='game_live_state'),
    path('games/<int:game_id>/gamecast/', GamecastView.as_view(), name='gamecast'),
    path('practice-sandbox/', PracticeSandboxView.as_view(), name='practice_sandbox'),

    # -------------------------------------------------------------------------
    # 9. Score Confirmations, Disputes & Forfeits
    # -------------------------------------------------------------------------
    path('games/<int:game_id>/score/confirm/', ConfirmGameScoreView.as_view(), name='confirm_game_score'),
    path('games/<int:game_id>/score/dispute/', DisputeGameScoreView.as_view(), name='dispute_game_score'),
    path('games/<int:game_id>/score/resolve/', ResolveScoreDisputeView.as_view(), name='resolve_score_dispute'),
    path('scores/bulk-confirm/', BulkConfirmPendingScoresView.as_view(), name='bulk_confirm_pending_scores'),
    path('games/<int:game_id>/forfeit/', RecordGameForfeitView.as_view(), name='record_game_forfeit'),

    # -------------------------------------------------------------------------
    # 10. Venue Condition Hotline & 1-Click Relocation
    # -------------------------------------------------------------------------
    path('venues/<int:venue_id>/status/', UpdateVenueStatusView.as_view(), name='update_venue_status'),
    path('venues/<int:venue_id>/relocate/', RelocateVenueGamesView.as_view(), name='relocate_venue_games'),

    # -------------------------------------------------------------------------
    # 11. Disciplinary, Incident Reports & Sportsmanship Evaluations
    # -------------------------------------------------------------------------
    path('<int:league_id>/discipline/', ManageDisciplinaryHubView.as_view(), name='manage_disciplinary_hub'),
    path('discipline/<int:record_id>/reinstate/', ReinstateDisciplinaryPenaltyView.as_view(), name='reinstate_disciplinary_penalty'),
    path('games/<int:game_id>/incident/report/', ReportGameIncidentView.as_view(), name='report_game_incident'),
    path('games/<int:game_id>/sportsmanship/rate/', SubmitSportsmanshipRatingView.as_view(), name='submit_sportsmanship_rating'),
    path('<int:league_id>/sportsmanship/', ManageSportsmanshipDashboardView.as_view(), name='manage_sportsmanship_dashboard'),
]
