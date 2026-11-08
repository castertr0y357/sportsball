"""
Domain scoring engine for diamond and court sports.
Encapsulates pitch-count tracking, runner advancement, run limit enforcement,
side retirement, volleyball sets, basketball fouls/timeouts, and undo snapshots.
"""

from __future__ import annotations
from typing import Any, Optional
from django.contrib.auth import get_user_model
from django.utils import timezone
from leagues.models import Game, GameLineupEntry, Team
from stats.models import PlayerGameStat
from core.services.notifications import send_discord_notification


COUNT_TERMINATING_ACTIONS = (
    'single', 'double', 'triple', 'homerun', 'walk', 'out',
    'strikeout', 'sacrifice_fly', 'rbi_groundout', 'fielders_choice',
    'reached_on_error'
)


def serialize_batter(player) -> Optional[dict[str, Any]]:
    """Serializes the current batter profile and walk-up music data."""
    if not player:
        return None
    return {
        'id': player.id,
        'name': player.display_name,
        'jersey_number': player.jersey_number,
        'walkup_song_title': player.walkup_song_title or '',
        'walkup_song_url': player.walkup_song_file.url if player.walkup_song_file else '',
        'walkup_start_seconds': player.walkup_start_seconds,
        'walkup_duration_seconds': player.walkup_duration_seconds,
    }


def serialize_game_state(game: Game) -> dict[str, Any]:
    """Generates a complete snapshot of live game state for the client."""
    batting_team = game.batting_team
    on_deck = game.peek_on_deck_batter()
    team1_lineup = [
        {
            'entry_id': e.id,
            'order': e.batting_order,
            'player_id': e.player.id,
            'name': e.player.display_name,
            'jersey': e.player.jersey_number,
            'is_present': e.is_present,
            'position': e.get_position_for_inning(game.current_inning) or e.field_position,
            'base_position': e.field_position,
            'has_walkup': bool(e.player.walkup_song_file or e.player.walkup_song_title),
            'walkup_title': e.player.walkup_song_title,
        }
        for e in game.lineup_entries.filter(team=game.team1).select_related('player').order_by('batting_order', 'id')
    ]
    team2_lineup = [
        {
            'entry_id': e.id,
            'order': e.batting_order,
            'player_id': e.player.id,
            'name': e.player.display_name,
            'jersey': e.player.jersey_number,
            'is_present': e.is_present,
            'position': e.get_position_for_inning(game.current_inning) or e.field_position,
            'base_position': e.field_position,
            'has_walkup': bool(e.player.walkup_song_file or e.player.walkup_song_title),
            'walkup_title': e.player.walkup_song_title,
        }
        for e in game.lineup_entries.filter(team=game.team2).select_related('player').order_by('batting_order', 'id')
    ]
    return {
        'game_id': game.id,
        'status': game.status,
        'status_display': game.get_status_display(),
        'team1_name': game.team1.name,
        'team2_name': game.team2.name,
        'team1_score': game.team1_score,
        'team2_score': game.team2_score,
        'team1_hits': game.team1_hits,
        'team2_hits': game.team2_hits,
        'active_scorer_id': game.active_scorer_id,
        'active_scorer_name': game.active_scorer.display_name if game.active_scorer else None,
        'active_scorer_expires_at': game.active_scorer_expires_at.isoformat() if game.active_scorer_expires_at else None,
        'score_confirmed': game.score_confirmed,
        'has_assigned_official': game.has_assigned_official,
        'current_inning': game.current_inning,
        'inning_half': game.inning_half,
        'inning_half_display': 'Top' if game.inning_half == 'top' else 'Bottom',
        'batting_team_name': batting_team.name,
        'outs': game.outs,
        'runner_on_first': game.runner_on_first,
        'runner_on_second': game.runner_on_second,
        'runner_on_third': game.runner_on_third,
        'current_batter': serialize_batter(game.current_batter),
        'on_deck_batter': serialize_batter(on_deck),
        'play_by_play': game.play_by_play or [],
        'team1_lineup': team1_lineup,
        'team2_lineup': team2_lineup,
        'is_diamond_sport': game.season.league.is_diamond_sport if game.season and game.season.league else False,
        'score_label': game.season.league.score_label if game.season and game.season.league else 'Points',
        'period_label': game.season.league.period_label if game.season and game.season.league else 'Period',
        'sport': game.season.league.sport if game.season and game.season.league else 'other',
        'enable_game_clock': game.season.league.enable_game_clock if game.season and game.season.league else False,
        'default_period_minutes': game.season.league.default_period_minutes if game.season and game.season.league else 20,
        'enable_flag_football_clocks': game.season.league.enable_flag_football_clocks if game.season and game.season.league else False,
        'enable_time_limit_clock': game.season.league.enable_time_limit_clock if game.season and game.season.league else False,
        'enable_timeout_clock': game.season.league.enable_timeout_clock if game.season and game.season.league else True,
        'clock_seconds_remaining': game.clock_seconds_remaining,
        'clock_running': game.clock_running,
        'balls': game.balls,
        'strikes': game.strikes,
        'courtesy_foul_used': game.courtesy_foul_used,
        'can_undo': bool(len(game.play_by_play_snapshots or []) > 0),
        'team1_fouls': game.team1_fouls,
        'team2_fouls': game.team2_fouls,
        'team1_bonus': bool(game.team1_fouls >= 7),
        'team1_double_bonus': bool(game.team1_fouls >= 10),
        'team2_bonus': bool(game.team2_fouls >= 7),
        'team2_double_bonus': bool(game.team2_fouls >= 10),
        'team1_timeouts_remaining': game.team1_timeouts_remaining,
        'team2_timeouts_remaining': game.team2_timeouts_remaining,
        'current_set': game.current_set,
        'volleyball_sets': game.volleyball_sets or [],
        'volleyball_serving_team_id': game.volleyball_serving_team_id,
        'volleyball_set_cap': game.season.league.volleyball_set_cap if game.season and game.season.league else 27,
        'volleyball_tiebreak_cap': game.season.league.volleyball_tiebreak_cap if game.season and game.season.league else 17,
        'foul_out_limit': game.season.league.foul_out_limit if game.season and game.season.league else 5,
        'inning_run_limit': game.season.league.inning_run_limit if game.season and game.season.league else None,
        'current_half_runs': game.current_half_runs,
        'mercy_rule_alert': game.check_mercy_rule(),
        'enable_time_limit_alert': game.season.league.enable_time_limit_alert if game.season and game.season.league else False,
        'game_time_limit_minutes': game.season.league.game_time_limit_minutes if game.season and game.season.league else 55,
        'no_new_inning_minutes': game.season.league.no_new_inning_minutes if game.season and game.season.league else 50,
        'softball_count_1_1_start': game.season.league.softball_count_1_1_start if game.season and game.season.league else True,
        'allow_courtesy_foul': game.season.league.allow_courtesy_foul if game.season and game.season.league else True,
        'enable_international_tiebreaker': game.season.league.enable_international_tiebreaker if game.season and game.season.league else False,
        'is_forfeit': game.is_forfeit,
        'forfeit_winner_name': game.forfeit_winner.name if game.forfeit_winner else None,
    }


def increment_player_stat(player, game: Game, team: Team, category: str, delta: int = 1) -> None:
    """Safely increments a player's individual game statistic."""
    if not player:
        return
    stat, created = PlayerGameStat.objects.get_or_create(
        player=player,
        game=game,
        category=category,
        defaults={'team': team, 'value': delta}
    )
    if not created:
        stat.value = max(0, stat.value + delta)
        stat.save(update_fields=['value'])


def check_inning_run_limit(game: Game, runs_added: int) -> bool:
    """Checks if batting team reached the inning run limit and auto-retires side if met."""
    if not runs_added:
        return False
    game.current_half_runs += runs_added
    league = game.season.league if (game.season and game.season.league) else None
    if not league or not league.inning_run_limit:
        return False
    if league.unlimited_runs_final_inning and game.current_inning >= 7:
        return False
    if game.current_half_runs >= league.inning_run_limit:
        handle_side_retired(game, reason=f"Inning run limit of {league.inning_run_limit} runs reached")
        return True
    return False


def handle_side_retired(game: Game, reason: str = "3 outs recorded") -> None:
    """Switches half inning, clears base runners, resets outs, and advances batter."""
    game.outs = 0
    game.current_half_runs = 0
    game.runner_on_first = False
    game.runner_on_second = False
    game.runner_on_third = False
    if game.inning_half == 'top':
        game.inning_half = 'bottom'
        game.log_play(f"Side retired ({reason})! Switching to Bottom of Inning {game.current_inning} ({game.team1.name} batting).")
    else:
        game.inning_half = 'top'
        game.current_inning += 1
        game.log_play(f"Side retired ({reason})! Switching to Top of Inning {game.current_inning} ({game.team2.name} batting).")
    game.advance_to_next_batter()


def apply_walk_outcome(game: Game, batter, batting_team: Team, batter_name: str) -> None:
    """Handles bases loaded walk or runner advances on base on balls."""
    runs_scored = 0
    if game.runner_on_first and game.runner_on_second and game.runner_on_third:
        runs_scored = 1
    elif game.runner_on_first and game.runner_on_second:
        game.runner_on_third = True
    elif game.runner_on_first:
        game.runner_on_second = True
    game.runner_on_first = True

    if runs_scored:
        if batting_team == game.team1:
            game.team1_score += 1
        else:
            game.team2_score += 1
        increment_player_stat(batter, game, batting_team, 'Runs Batted In', 1)
        game.log_play(f"{batter_name} walks with bases loaded! (+1 run scores).")
    else:
        game.log_play(f"{batter_name} reaches first base (Walk / BB).")

    side_retired = check_inning_run_limit(game, runs_scored)
    if not side_retired:
        game.advance_to_next_batter()


def apply_dugout_action_internal(game: Game, action: str, payload: dict[str, Any]) -> bool:
    """
    Core state machine logic executing sport actions (diamond, court, clock, lineups).
    Returns True if walk-up music should be triggered.
    """
    trigger_walkup = False
    if game.status == 'scheduled' and action not in ('toggle_attendance', 'move_lineup'):
        game.status = 'in_progress'

    batting_team = game.batting_team
    batter = game.current_batter
    batter_name = batter.display_name if batter else batting_team.name

    if action == 'next_batter':
        new_batter = game.advance_to_next_batter()
        trigger_walkup = True
        if new_batter:
            game.log_play(f"Now batting for {batting_team.name}: #{new_batter.jersey_number or '-'} {new_batter.display_name}")

    elif action == 'single':
        if batting_team == game.team1:
            game.team1_hits += 1
        else:
            game.team2_hits += 1
        increment_player_stat(batter, game, batting_team, 'Hits', 1)

        runs_scored = 0
        if game.runner_on_third:
            runs_scored += 1
            game.runner_on_third = False
        if game.runner_on_second:
            game.runner_on_third = True
            game.runner_on_second = False
        if game.runner_on_first:
            game.runner_on_second = True
        game.runner_on_first = True

        if runs_scored:
            if batting_team == game.team1:
                game.team1_score += runs_scored
            else:
                game.team2_score += runs_scored
            increment_player_stat(batter, game, batting_team, 'Runs Batted In', runs_scored)
            game.log_play(f"{batter_name} singles! ({runs_scored} run scores)")
        else:
            game.log_play(f"{batter_name} hits a single (runner on 1B).")

        side_retired = check_inning_run_limit(game, runs_scored)
        if not side_retired:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'double':
        if batting_team == game.team1:
            game.team1_hits += 1
        else:
            game.team2_hits += 1
        increment_player_stat(batter, game, batting_team, 'Hits', 1)

        runs_scored = 0
        if game.runner_on_third:
            runs_scored += 1
            game.runner_on_third = False
        if game.runner_on_second:
            runs_scored += 1
            game.runner_on_second = False
        runner_on_first_to_third = False
        if game.runner_on_first:
            runner_on_first_to_third = True
            game.runner_on_first = False

        game.runner_on_second = True
        if runner_on_first_to_third:
            game.runner_on_third = True

        if runs_scored:
            if batting_team == game.team1:
                game.team1_score += runs_scored
            else:
                game.team2_score += runs_scored
            increment_player_stat(batter, game, batting_team, 'Runs Batted In', runs_scored)
            game.log_play(f"{batter_name} doubles! ({runs_scored} run(s) scored)")
        else:
            game.log_play(f"{batter_name} hits a double (runner on 2B).")

        side_retired = check_inning_run_limit(game, runs_scored)
        if not side_retired:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'triple':
        if batting_team == game.team1:
            game.team1_hits += 1
        else:
            game.team2_hits += 1
        increment_player_stat(batter, game, batting_team, 'Hits', 1)

        runs_scored = int(game.runner_on_first) + int(game.runner_on_second) + int(game.runner_on_third)
        game.runner_on_first = False
        game.runner_on_second = False
        game.runner_on_third = True

        if runs_scored:
            if batting_team == game.team1:
                game.team1_score += runs_scored
            else:
                game.team2_score += runs_scored
            increment_player_stat(batter, game, batting_team, 'Runs Batted In', runs_scored)
            game.log_play(f"{batter_name} triples! ({runs_scored} run(s) scored)")
        else:
            game.log_play(f"{batter_name} hits a triple (runner on 3B).")

        side_retired = check_inning_run_limit(game, runs_scored)
        if not side_retired:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'walk':
        apply_walk_outcome(game, batter, batting_team, batter_name)
        trigger_walkup = True

    elif action == 'homerun':
        runners = int(game.runner_on_first) + int(game.runner_on_second) + int(game.runner_on_third)
        runs_scored = runners + 1
        if batting_team == game.team1:
            game.team1_hits += 1
            game.team1_score += runs_scored
        else:
            game.team2_hits += 1
            game.team2_score += runs_scored

        game.runner_on_first = False
        game.runner_on_second = False
        game.runner_on_third = False

        increment_player_stat(batter, game, batting_team, 'Hits', 1)
        increment_player_stat(batter, game, batting_team, 'Home Runs', 1)
        increment_player_stat(batter, game, batting_team, 'Runs Batted In', runs_scored)
        increment_player_stat(batter, game, batting_team, 'Runs Scored', 1)

        game.log_play(f"HOME RUN by {batter_name}! ({runs_scored} R scored)")
        side_retired = check_inning_run_limit(game, runs_scored)
        if not side_retired:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'out':
        game.outs += 1
        if game.outs >= 3:
            handle_side_retired(game, reason="3 outs recorded")
        else:
            game.log_play(f"{batter_name} recorded out ({game.outs} out).")
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action in ('sacrifice_fly', 'rbi_groundout'):
        game.outs += 1
        runs_scored = 0
        if game.runner_on_third:
            runs_scored = 1
            game.runner_on_third = False
            if batting_team == game.team1:
                game.team1_score += 1
            else:
                game.team2_score += 1
            increment_player_stat(batter, game, batting_team, 'Runs Batted In', 1)

        act_label = "Sacrifice Fly" if action == 'sacrifice_fly' else "RBI Groundout"
        if runs_scored:
            game.log_play(f"{batter_name} hits {act_label}. Run scores! ({game.outs} out)")
        else:
            game.log_play(f"{batter_name} recorded out ({game.outs} out).")

        side_retired = check_inning_run_limit(game, runs_scored)
        if not side_retired:
            if game.outs >= 3:
                handle_side_retired(game, reason="3 outs recorded")
            else:
                game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'fielders_choice':
        game.outs += 1
        if game.runner_on_third:
            game.runner_on_third = False
        elif game.runner_on_second:
            game.runner_on_second = False
        elif game.runner_on_first:
            game.runner_on_first = False
        game.runner_on_first = True

        game.log_play(f"{batter_name} reaches on Fielder's Choice (out on basepaths, {game.outs} out).")
        if game.outs >= 3:
            handle_side_retired(game, reason="3 outs recorded")
        else:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'strikeout':
        game.outs += 1
        style = payload.get('style', 'swinging')
        style_label = "swinging (K)" if style == 'swinging' else "looking (ꓘ)"
        game.log_play(f"{batter_name} strikes out {style_label} ({game.outs} out).")
        if game.outs >= 3:
            handle_side_retired(game, reason="3 outs recorded")
        else:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'reached_on_error':
        runs_scored = 0
        if game.runner_on_third:
            runs_scored += 1
            game.runner_on_third = False
        if game.runner_on_second:
            game.runner_on_third = True
            game.runner_on_second = False
        if game.runner_on_first:
            game.runner_on_second = True
        game.runner_on_first = True

        if runs_scored:
            if batting_team == game.team1:
                game.team1_score += runs_scored
            else:
                game.team2_score += runs_scored
            game.log_play(f"{batter_name} reaches on Error (E)! ({runs_scored} run(s) scored)")
        else:
            game.log_play(f"{batter_name} reaches on Error (E).")

        side_retired = check_inning_run_limit(game, runs_scored)
        if not side_retired:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'advance_runner':
        from_base = payload.get('from_base')
        to_base = payload.get('to_base')
        if from_base == '1B': game.runner_on_first = False
        elif from_base == '2B': game.runner_on_second = False
        elif from_base == '3B': game.runner_on_third = False

        if to_base == 'home':
            if batting_team == game.team1:
                game.team1_score += 1
            else:
                game.team2_score += 1
            game.log_play(f"Runner advances home and scores (+1 run for {batting_team.name})!")
            check_inning_run_limit(game, 1)
        elif to_base == 'out':
            game.outs += 1
            game.log_play(f"Runner put out on basepath from {from_base} ({game.outs} out).")
            if game.outs >= 3:
                handle_side_retired(game, reason="3 outs recorded")
        elif to_base == '2B':
            game.runner_on_second = True
            game.log_play("Runner advanced to 2B.")
        elif to_base == '3B':
            game.runner_on_third = True
            game.log_play("Runner advanced to 3B.")

    elif action in ('double_play', 'triple_play'):
        outs_added = 2 if action == 'double_play' else 3
        game.outs += outs_added
        label = "DOUBLE PLAY (DP)" if action == 'double_play' else "TRIPLE PLAY (TP)"
        game.log_play(f"Defensive {label}! ({game.outs} out).")
        if game.outs >= 3:
            handle_side_retired(game, reason=f"{label} recorded")
        else:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'count_ball':
        game.balls += 1
        if game.balls >= 4:
            apply_walk_outcome(game, batter, batting_team, batter_name)
            trigger_walkup = True
        else:
            game.log_play(f"Ball {game.balls} to {batter_name} (Count: {game.balls}-{game.strikes}).")

    elif action == 'count_strike':
        game.strikes += 1
        if game.strikes >= 3:
            game.outs += 1
            game.log_play(f"{batter_name} strikes out on Strike 3 ({game.outs} out).")
            if game.outs >= 3:
                handle_side_retired(game, reason="3 outs recorded")
            else:
                game.advance_to_next_batter()
            trigger_walkup = True
        else:
            game.log_play(f"Strike {game.strikes} on {batter_name} (Count: {game.balls}-{game.strikes}).")

    elif action == 'count_foul':
        league = game.season.league if (game.season and game.season.league) else None
        allow_courtesy = league.allow_courtesy_foul if league else True
        if game.strikes < 2:
            game.strikes += 1
            game.log_play(f"Foul ball by {batter_name} (Count: {game.balls}-{game.strikes}).")
        elif game.strikes >= 2:
            if allow_courtesy and not game.courtesy_foul_used:
                game.courtesy_foul_used = True
                game.log_play(f"Foul ball by {batter_name} (Courtesy Foul used).")
            else:
                game.outs += 1
                game.log_play(f"Foul ball with 2 strikes — Strike 3! {batter_name} out ({game.outs} out).")
                if game.outs >= 3:
                    handle_side_retired(game, reason="3 outs recorded")
                else:
                    game.advance_to_next_batter()
                trigger_walkup = True

    elif action == 'reset_count':
        game.reset_batter_count()
        game.log_play(f"Count reset to {game.balls}-{game.strikes} for {batter_name}.")

    elif action == 'international_tiebreaker':
        game.runner_on_second = True
        game.outs = 0
        game.log_play(f"International Tiebreaker: Runner placed on 2B for {batting_team.name} with 0 outs.")

    elif action == 'run_plus':
        team_target = payload.get('team', 'batting')
        points = int(payload.get('points', 1))
        label = game.season.league.score_label if (game.season and game.season.league) else 'Pts'
        if team_target == 'team1' or (team_target == 'batting' and batting_team == game.team1):
            game.team1_score += points
            game.log_play(f"+{points} {label} for {game.team1.name} ({game.team1_score}-{game.team2_score}).")
            if game.season and game.season.league and game.season.league.is_diamond_sport:
                check_inning_run_limit(game, points)
        else:
            game.team2_score += points
            game.log_play(f"+{points} {label} for {game.team2.name} ({game.team1_score}-{game.team2_score}).")
            if game.season and game.season.league and game.season.league.is_diamond_sport:
                check_inning_run_limit(game, points)

    elif action == 'run_minus':
        team_target = payload.get('team', 'batting')
        points = int(payload.get('points', 1))
        if team_target == 'team1':
            game.team1_score = max(0, game.team1_score - points)
        else:
            game.team2_score = max(0, game.team2_score - points)

    elif action == 'toggle_base':
        base = payload.get('base')
        if base == '1B':
            game.runner_on_first = not game.runner_on_first
        elif base == '2B':
            game.runner_on_second = not game.runner_on_second
        elif base == '3B':
            game.runner_on_third = not game.runner_on_third

    elif action == 'flip_half':
        game.outs = 0
        game.current_half_runs = 0
        game.runner_on_first = False
        game.runner_on_second = False
        game.runner_on_third = False
        if game.inning_half == 'top':
            game.inning_half = 'bottom'
        else:
            game.inning_half = 'top'
            game.current_inning += 1
        game.advance_to_next_batter()
        trigger_walkup = True
        game.log_play(f"Half-inning advanced to {'Top' if game.inning_half == 'top' else 'Bottom'} {game.current_inning}.")

    elif action == 'clock_update':
        if 'remaining' in payload:
            game.clock_seconds_remaining = int(payload['remaining'])
        if 'running' in payload:
            game.clock_running = bool(payload['running'])
            game.clock_last_started_at = timezone.now() if game.clock_running else None

    elif action == 'team_foul':
        target_team_code = payload.get('team', 'team1')
        if target_team_code == 'team1':
            game.team1_fouls += 1
            foul_count = game.team1_fouls
            t_name = game.team1.name
        else:
            game.team2_fouls += 1
            foul_count = game.team2_fouls
            t_name = game.team2.name

        bonus_str = ""
        if foul_count == 7:
            bonus_str = " (BONUS 1-and-1 Active!)"
        elif foul_count >= 10:
            bonus_str = " (DOUBLE BONUS 2-Shots Active!)"
        game.log_play(f"Team foul on {t_name} (Foul #{foul_count}){bonus_str}.")

    elif action == 'reset_fouls_half':
        game.team1_fouls = 0
        game.team2_fouls = 0
        game.log_play("Team fouls reset for new period/half.")

    elif action == 'use_timeout':
        target_team_code = payload.get('team', 'team1')
        if target_team_code == 'team1':
            game.team1_timeouts_remaining = max(0, game.team1_timeouts_remaining - 1)
            rem = game.team1_timeouts_remaining
            t_name = game.team1.name
        else:
            game.team2_timeouts_remaining = max(0, game.team2_timeouts_remaining - 1)
            rem = game.team2_timeouts_remaining
            t_name = game.team2.name
        game.log_play(f"Timeout called by {t_name} ({rem} remaining).")

    elif action == 'player_foul':
        player_id = payload.get('player_id')
        player = get_user_model().objects.filter(id=player_id).first()
        if player:
            increment_player_stat(player, game, batting_team, 'Fouls', 1)
            stat = PlayerGameStat.objects.filter(player=player, game=game, category='Fouls').first()
            foul_val = stat.value if stat else 1
            limit = game.season.league.foul_out_limit if (game.season and game.season.league) else 5
            jersey = f"#{player.jersey_number} " if player.jersey_number else ""
            if foul_val >= limit:
                game.log_play(f"⚠️ [FOUL OUT] {jersey}{player.display_name} committed foul #{foul_val} and is disqualified!")
            else:
                game.log_play(f"Personal foul on {jersey}{player.display_name} (Foul #{foul_val}).")

    elif action == 'volleyball_point':
        target_team_code = payload.get('team', 'team1')
        if target_team_code == 'team1':
            game.team1_score += 1
            t_name = game.team1.name
            t_score = game.team1_score
            opp_score = game.team2_score
        else:
            game.team2_score += 1
            t_name = game.team2.name
            t_score = game.team2_score
            opp_score = game.team1_score

        league = game.season.league if (game.season and game.season.league) else None
        target_pts = 15 if game.current_set >= 3 else 25
        cap = (league.volleyball_tiebreak_cap if game.current_set >= 3 else league.volleyball_set_cap) if league else (17 if game.current_set >= 3 else 27)

        is_set_win = (t_score >= target_pts and (t_score - opp_score) >= 2) or (cap and t_score >= cap)
        if is_set_win:
            winner_team = game.team1 if target_team_code == 'team1' else game.team2
            v_sets = list(game.volleyball_sets or [])
            v_sets.append({
                'set': game.current_set,
                'team1_score': game.team1_score,
                'team2_score': game.team2_score,
                'winner': winner_team.name,
                'winner_id': winner_team.id,
            })
            game.volleyball_sets = v_sets
            game.log_play(f"🏐 SET {game.current_set} FINAL: {winner_team.name} wins set {game.team1_score}-{game.team2_score}!")
            game.current_set += 1
            game.team1_score = 0
            game.team2_score = 0
        else:
            game.log_play(f"Point for {t_name} (Set {game.current_set}: {game.team1_score}-{game.team2_score}).")

    elif action == 'switch_serve':
        if game.volleyball_serving_team_id == game.team1_id:
            game.volleyball_serving_team = game.team2
        else:
            game.volleyball_serving_team = game.team1
        game.log_play(f"Service to {game.volleyball_serving_team.name}.")

    elif action == 'flag_dispute':
        notes = payload.get('notes', 'Rule interpretation disputed by coach')
        game.log_score_event(
            game.active_scorer or None,
            'rule_protest',
            f"Rule Protest: {notes} | Inn/Period {game.current_inning} ({game.inning_half}), Score {game.team1_score}-{game.team2_score}"
        )
        game.log_play(f"⚖️ [RULE PROTEST] {notes}")

    elif action == 'record_forfeit':
        winner_id = payload.get('winner_id')
        winner_team = game.team1 if str(winner_id) == str(game.team1_id) else game.team2
        notes = payload.get('notes', 'Official forfeit recorded by scorekeeper')
        game.record_forfeit(winning_team=winner_team, recording_user=game.active_scorer, notes=notes)

    elif action == 'mark_final':
        game.status = 'completed'
        game.log_play(f"FINAL SCORE: {game.team1.name} {game.team1_score}, {game.team2.name} {game.team2_score}")

        webhook = (game.season.discord_webhook_url if game.season else '') or (game.season.league.discord_webhook_url if game.season and game.season.league else '')
        if webhook:
            winner_str = f"Winner: {game.winner.name}" if game.winner else "Result: Tie"
            send_discord_notification(
                webhook_url=webhook,
                title=f"Final Score: {game.team1.name} vs {game.team2.name}",
                description=f"**{game.team1.name} {game.team1_score}**  —  **{game.team2_score} {game.team2.name}**\n{winner_str}",
                color=0x15803d
            )

    elif action == 'toggle_attendance':
        entry_id = payload.get('entry_id')
        entry = GameLineupEntry.objects.filter(id=entry_id, game=game).first()
        if entry:
            entry.is_present = not entry.is_present
            entry.save(update_fields=['is_present'])
            if not entry.is_present and game.current_batter_id == entry.player_id:
                game.advance_to_next_batter()

    elif action == 'substitute_player':
        out_entry_id = payload.get('out_entry_id')
        in_entry_id = payload.get('in_entry_id')
        out_entry = GameLineupEntry.objects.filter(id=out_entry_id, game=game).first()
        in_entry = GameLineupEntry.objects.filter(id=in_entry_id, game=game).first()
        if out_entry and in_entry and out_entry.team_id == in_entry.team_id:
            out_order = out_entry.batting_order
            out_pos = out_entry.field_position
            out_entry.is_present = False
            out_entry.save(update_fields=['is_present'])

            in_entry.batting_order = out_order
            in_entry.field_position = out_pos
            in_entry.is_present = True
            in_entry.save(update_fields=['batting_order', 'field_position', 'is_present'])

            if game.current_batter_id == out_entry.player_id:
                game.current_batter = in_entry.player
                trigger_walkup = True

            jersey_out = f"#{out_entry.player.jersey_number} " if out_entry.player.jersey_number else ""
            jersey_in = f"#{in_entry.player.jersey_number} " if in_entry.player.jersey_number else ""
            game.log_play(f"[SUB] Inning {game.current_inning}: {jersey_in}{in_entry.player.display_name} in for {jersey_out}{out_entry.player.display_name} (Spot #{out_order}).")

    elif action == 'move_lineup':
        entry_id = payload.get('entry_id')
        direction = payload.get('direction', 'up')
        entry = GameLineupEntry.objects.filter(id=entry_id, game=game).first()
        if entry:
            siblings = list(GameLineupEntry.objects.filter(game=game, team=entry.team).order_by('batting_order', 'id'))
            idx = next((i for i, e in enumerate(siblings) if e.id == entry.id), None)
            if idx is not None:
                swap_idx = idx - 1 if direction == 'up' else idx + 1
                if 0 <= swap_idx < len(siblings):
                    siblings[idx], siblings[swap_idx] = siblings[swap_idx], siblings[idx]
                    for new_order, item in enumerate(siblings, start=1):
                        if item.batting_order != new_order:
                            item.batting_order = new_order
                            item.save(update_fields=['batting_order'])

    return trigger_walkup


def apply_scoring_action(game: Game, action: str, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """
    High-level entrypoint for scoring:
    - Automatically manages 10-state undo stack
    - Executes undo if requested
    - Enforces count termination resets
    - Executes action state transitions
    - Enforces tiered mercy rules
    - Saves game and returns (trigger_walkup, serialized_state)
    """
    if action == 'undo':
        undone = game.pop_snapshot()
        if undone:
            game.save()
            return False, serialize_game_state(game)
        else:
            return False, serialize_game_state(game)

    # Push state to undo stack before mutating
    game.push_snapshot()

    # Reset batter count on plate-appearance ending actions
    if action in COUNT_TERMINATING_ACTIONS:
        game.reset_batter_count()

    trigger_walkup = apply_dugout_action_internal(game, action, payload)

    # Automated Tiered Mercy Rule Check
    if action in ('single', 'double', 'triple', 'homerun', 'walk', 'run_plus', 'reached_on_error', 'sacrifice_fly'):
        game.check_mercy_rule()

    game.save()
    return trigger_walkup, serialize_game_state(game)
