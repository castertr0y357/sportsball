"""
Package export module for leagues.views.
Exposes all Class-Based Views (CBVs) as well as backwards-compatible callable view functions
and internal domain helpers so no existing URL patterns, test fixtures, or external modules break.
"""

# Mixins
from leagues.views.mixins import (
    LeagueAdminRequiredMixin,
    SeasonAdminRequiredMixin,
    TeamCoachRequiredMixin,
    ScorekeeperAccessMixin,
    JsonResponseMixin,
)

# League & Pool views
from leagues.views.league_views import (
    LeagueListView,
    LeagueCreateView,
    LeaguePoolsView,
    AddLeagueVenueView,
    ToggleLeagueVenueView,
    DeleteLeagueVenueView,
    AddLeagueOfficialView,
    RemoveLeagueOfficialView,
)

# Season & Rainout views
from leagues.views.season_views import (
    SeasonListView,
    SeasonCreateView,
    SeasonDetailView,
    SeasonCalendarIcsView,
    RainoutTodayGamesView,
    RescheduleRainoutsView,
)

# Team & Roster views
from leagues.views.team_views import (
    TeamListView,
    TeamCreateView,
    TeamDetailView,
    ManageRosterPlayerView,
    JoinTeamView,
    JoinTeamByInviteView,
    ToggleTeamDuesView,
    TeamCalendarIcsView,
    TeamSafetyRosterView,
    team_safety_roster,
)

# Registration views
from leagues.views.registration_views import (
    RegisterForSeasonView,
    AssignRegistrationView,
    ImportSeasonTeamsView,
)

# Scheduling & Playoff views
from leagues.views.schedule_views import (
    CreateGameView,
    GenerateScheduleView,
    PlayoffBracketView,
    GeneratePlayoffsView,
    AdvancePlayoffsToFinalView,
    ScheduleGridView,
    SwapGameSlotsView,
)

# Officials views
from leagues.views.officials_views import (
    OfficialsHubView,
    RespondOfficialAssignmentView,
    ClaimOfficialAssignmentView,
    ToggleOfficialPaymentView,
)

# Game & Lineup views
from leagues.views.game_views import (
    GameDetailView,
    RecordGameScoreView,
    AddGameStatView,
    GameRSVPView,
    GameLineupBuilderView,
    GameLineupPrintView,
    UserCalendarIcsView,
)

# Dugout & Scoring views
from leagues.views.dugout_views import (
    DugoutConsoleView,
    DugoutActionView,
    DugoutBatchSyncView,
    GameLiveStateView,
    GamecastView,
    PracticeSandboxView,
    TakeOverDugoutScoringView,
)

# Dispute & Forfeit views
from leagues.views.dispute_views import (
    ConfirmGameScoreView,
    DisputeGameScoreView,
    ResolveScoreDisputeView,
    BulkConfirmPendingScoresView,
    RecordGameForfeitView,
)

# Venue views
from leagues.views.venue_views import (
    UpdateVenueStatusView,
    RelocateVenueGamesView,
)

# Discipline & Conduct views
from leagues.views.discipline_views import (
    ManageDisciplinaryHubView,
    ReinstateDisciplinaryPenaltyView,
    ReportGameIncidentView,
    SubmitSportsmanshipRatingView,
    ManageSportsmanshipDashboardView,
)

# Domain services & helpers for backward compatibility
from leagues.services import scoring_engine
_serialize_batter = scoring_engine.serialize_batter
_serialize_game_state = scoring_engine.serialize_game_state
_increment_player_stat = scoring_engine.increment_player_stat
_check_inning_run_limit = scoring_engine.check_inning_run_limit
_handle_side_retired = scoring_engine.handle_side_retired
_apply_walk_outcome = scoring_engine.apply_walk_outcome
_apply_dugout_action_internal = scoring_engine.apply_dugout_action_internal

# ============================================================================
# Backward-Compatible Callable View Functions (.as_view() wrappers)
# ============================================================================
league_list = LeagueListView.as_view()
create_league = LeagueCreateView.as_view()
season_list = SeasonListView.as_view()
create_season = SeasonCreateView.as_view()
season_detail = SeasonDetailView.as_view()
team_list = TeamListView.as_view()
create_team = TeamCreateView.as_view()
team_detail = TeamDetailView.as_view()
manage_roster_player = ManageRosterPlayerView.as_view()
join_team = JoinTeamView.as_view()
join_team_by_invite = JoinTeamByInviteView.as_view()
register_for_season = RegisterForSeasonView.as_view()
assign_registration = AssignRegistrationView.as_view()
create_game = CreateGameView.as_view()
generate_schedule = GenerateScheduleView.as_view()
generate_playoffs = GeneratePlayoffsView.as_view()
advance_playoffs_to_final = AdvancePlayoffsToFinalView.as_view()
playoff_bracket = PlayoffBracketView.as_view()
game_detail = GameDetailView.as_view()
record_game_score = RecordGameScoreView.as_view()
add_game_stat = AddGameStatView.as_view()
dugout_console = DugoutConsoleView.as_view()
dugout_action = DugoutActionView.as_view()
dugout_batch_sync = DugoutBatchSyncView.as_view()
game_live_state = GameLiveStateView.as_view()
gamecast = GamecastView.as_view()
practice_sandbox = PracticeSandboxView.as_view()
game_rsvp = GameRSVPView.as_view()
game_lineup_builder = GameLineupBuilderView.as_view()
game_lineup_print = GameLineupPrintView.as_view()
team_calendar_ics = TeamCalendarIcsView.as_view()
season_calendar_ics = SeasonCalendarIcsView.as_view()
user_calendar_ics = UserCalendarIcsView.as_view()
rainout_today_games = RainoutTodayGamesView.as_view()
schedule_grid = ScheduleGridView.as_view()
swap_game_slots = SwapGameSlotsView.as_view()
officials_hub = OfficialsHubView.as_view()
respond_official_assignment = RespondOfficialAssignmentView.as_view()
claim_official_assignment = ClaimOfficialAssignmentView.as_view()
toggle_team_dues = ToggleTeamDuesView.as_view()
take_over_dugout_scoring = TakeOverDugoutScoringView.as_view()
confirm_game_score = ConfirmGameScoreView.as_view()
dispute_game_score = DisputeGameScoreView.as_view()
resolve_score_dispute = ResolveScoreDisputeView.as_view()
bulk_confirm_pending_scores = BulkConfirmPendingScoresView.as_view()
record_game_forfeit = RecordGameForfeitView.as_view()
toggle_official_payment = ToggleOfficialPaymentView.as_view()
reschedule_rainouts = RescheduleRainoutsView.as_view()
manage_league_pools = LeaguePoolsView.as_view()
add_league_venue = AddLeagueVenueView.as_view()
toggle_league_venue = ToggleLeagueVenueView.as_view()
delete_league_venue = DeleteLeagueVenueView.as_view()
add_league_official = AddLeagueOfficialView.as_view()
remove_league_official = RemoveLeagueOfficialView.as_view()
import_season_teams = ImportSeasonTeamsView.as_view()
manage_disciplinary_hub = ManageDisciplinaryHubView.as_view()
reinstate_disciplinary_penalty = ReinstateDisciplinaryPenaltyView.as_view()
report_game_incident = ReportGameIncidentView.as_view()
update_venue_status = UpdateVenueStatusView.as_view()
relocate_venue_games = RelocateVenueGamesView.as_view()
submit_sportsmanship_rating = SubmitSportsmanshipRatingView.as_view()
manage_sportsmanship_dashboard = ManageSportsmanshipDashboardView.as_view()
