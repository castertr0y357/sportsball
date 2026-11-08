"""
Domain discipline and sportsmanship service.
Manages player conduct records, suspensions, expulsions, early reinstatements,
incident reports, and sportsmanship evaluations.
"""

from __future__ import annotations
from datetime import date
from typing import Optional, Any
from django.utils import timezone
from leagues.models import League, Team, Game, PlayerDisciplinaryRecord, GameSportsmanshipRating
from core.services.notifications import send_discord_notification
from users.models import CustomUser


def create_disciplinary_action(
    league: League,
    player: CustomUser,
    issued_by: CustomUser,
    penalty_type: str,
    reason: str,
    team: Optional[Team] = None,
    games_count: int = 1,
    suspended_until: Optional[date] = None,
    dues_forfeited: bool = False
) -> PlayerDisciplinaryRecord:
    """Creates a player disciplinary record and updates user account if expulsion."""
    rec = PlayerDisciplinaryRecord.objects.create(
        player=player,
        league=league,
        team=team,
        penalty_type=penalty_type,
        status='active',
        games_suspended_total=games_count if penalty_type == 'game_count' else 0,
        suspended_until=suspended_until if penalty_type == 'date_bound' else None,
        dues_forfeited=dues_forfeited,
        reason=reason,
        issued_by=issued_by
    )

    if penalty_type == 'permanent_expulsion':
        player.is_expelled = True
        player.expulsion_reason = reason
        player.is_active = False
        player.save(update_fields=['is_expelled', 'expulsion_reason', 'is_active'])

    if league.discord_webhook_url:
        send_discord_notification(
            league.discord_webhook_url,
            f"⚖️ League Disciplinary Notice ({league.name}): {player.display_name} issued {rec.get_penalty_type_display()}. Rationale: {reason}"
        )

    return rec


def reinstate_player_penalty(record: PlayerDisciplinaryRecord, notes: str, reinstated_by: CustomUser) -> None:
    """Lifts an active suspension early and restores account if expelled."""
    record.status = 'rescinded'
    record.reinstated_at = timezone.now()
    record.resolution_notes = f"{record.resolution_notes}\n[RESCINDED by {reinstated_by.display_name}]: {notes or 'Early reinstatement approved.'}".strip()
    record.save(update_fields=['status', 'reinstated_at', 'resolution_notes'])

    if record.penalty_type == 'permanent_expulsion':
        record.player.is_expelled = False
        record.player.is_active = True
        record.player.save(update_fields=['is_expelled', 'is_active'])


def record_incident_report(
    game: Game,
    player: CustomUser,
    reporting_user: CustomUser,
    incident_type: str,
    description: str,
    is_ejection: bool
) -> tuple[Optional[PlayerDisciplinaryRecord], str]:
    """
    Logs an incident in the game audit trail.
    If an ejection, automatically generates a 1-game suspension.
    """
    team = game.team1 if player in game.team1.players.all() else game.team2

    game.log_score_event(
        reporting_user,
        'incident_reported',
        f"Incident: {player.display_name} ({'EJECTION' if is_ejection else incident_type}): {description}"
    )

    rec = None
    msg = f"Recorded conduct incident report for {player.display_name}."
    if is_ejection and game.season and game.season.league:
        rec = PlayerDisciplinaryRecord.objects.create(
            player=player,
            league=game.season.league,
            team=team,
            game=game,
            penalty_type='game_count',
            status='active',
            games_suspended_total=1,
            reason=f"Game Ejection: {description}",
            issued_by=reporting_user
        )
        msg = f"⚠️ Recorded ejection for {player.display_name}. 1-game suspension active pending committee review."

    return rec, msg


def record_sportsmanship_rating(
    game: Game,
    rated_team: Team,
    evaluator: CustomUser,
    score: int,
    respect_for_officials: int,
    bench_conduct: int,
    notes: str = ""
) -> GameSportsmanshipRating:
    """Records or updates a team's sportsmanship evaluation."""
    is_official = (
        evaluator.role == 'referee' or
        (hasattr(game, 'official_assignments') and game.official_assignments.filter(official=evaluator).exists())
    )
    is_commish = evaluator.is_overall_commissioner or (game.season and evaluator.can_manage_league(game.season.league))

    if is_official:
        role = 'official'
    elif is_commish:
        role = 'commissioner'
    else:
        role = 'coach'

    rating, _ = GameSportsmanshipRating.objects.update_or_create(
        game=game,
        evaluator=evaluator,
        rated_team=rated_team,
        defaults={
            'evaluator_role': role,
            'score': max(1, min(5, score)),
            'respect_for_officials': max(1, min(5, respect_for_officials)),
            'bench_conduct': max(1, min(5, bench_conduct)),
            'notes': notes.strip(),
        }
    )
    return rating


def get_league_sportsmanship_rankings(league: League) -> list[dict[str, Any]]:
    """Returns sorted summary of all teams in a league by sportsmanship average."""
    teams = league.teams.all().select_related('church', 'captain', 'season')
    teams_summary = []
    for t in teams:
        summary = t.get_sportsmanship_summary()
        summary['team'] = t
        teams_summary.append(summary)

    # Sort lowest scores first so problem teams are immediately visible to committee
    teams_summary.sort(key=lambda s: (s['avg_score'], s['count']))
    return teams_summary
