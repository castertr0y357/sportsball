"""
Views for Disciplinary Hub, Player Reinstatements, Incident Reports,
Sportsmanship Evaluations, and League Renewal Dashboard.
"""

from __future__ import annotations
import datetime
from typing import Any
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import View
from leagues.models import League, Game, Team, PlayerDisciplinaryRecord
from leagues.views.mixins import LeagueAdminRequiredMixin
from leagues.services import discipline_service
from users.models import CustomUser


class ManageDisciplinaryHubView(LeagueAdminRequiredMixin, View):
    """Commissioner and Committee interface to review incidents, issue suspensions, or ban participants."""

    def get(self, request, league_id: int):
        league = self.get_league()
        records = PlayerDisciplinaryRecord.objects.filter(league=league).select_related('player', 'team', 'issued_by').order_by('-issued_at')
        active_records = [r for r in records if r.is_currently_active()]
        past_records = [r for r in records if not r.is_currently_active()]

        league_players = CustomUser.objects.filter(
            Q(teams__league=league) | Q(season_registrations__season__league=league)
        ).distinct().order_by('first_name', 'last_name')

        return render(request, 'leagues/disciplinary_hub.html', {
            'league': league,
            'records': records,
            'active_records': active_records,
            'past_records': past_records,
            'league_players': league_players,
            'league_teams': league.teams.all(),
        })

    def post(self, request, league_id: int):
        league = self.get_league()
        action = request.POST.get('action')

        if action == 'create_disciplinary_record':
            player_id = request.POST.get('player_id')
            team_id = request.POST.get('team_id') or None
            penalty_type = request.POST.get('penalty_type', 'game_count')
            reason = request.POST.get('reason', '').strip()
            games_count = int(request.POST.get('games_suspended_total', 1) or 1)
            suspended_until_str = request.POST.get('suspended_until')
            dues_forfeited = bool(request.POST.get('dues_forfeited'))

            suspended_until = None
            if suspended_until_str:
                try:
                    suspended_until = datetime.datetime.strptime(suspended_until_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            player = get_object_or_404(CustomUser, id=player_id)
            team = Team.objects.filter(id=team_id, league=league).first() if team_id else None

            rec = discipline_service.create_disciplinary_action(
                league=league,
                player=player,
                issued_by=request.user,
                penalty_type=penalty_type,
                reason=reason,
                team=team,
                games_count=games_count,
                suspended_until=suspended_until,
                dues_forfeited=dues_forfeited
            )

            if penalty_type == 'permanent_expulsion':
                messages.warning(request, f"⛔ Participant {player.display_name} has been permanently expelled. Account deactivated.")
            else:
                messages.success(request, f"Recorded disciplinary action for {player.display_name}: {rec.get_penalty_type_display()}.")

        return redirect('manage_disciplinary_hub', league_id=league.id)


class ReinstateDisciplinaryPenaltyView(LeagueAdminRequiredMixin, View):
    """Allows commissioner to rescind/lift an active suspension early."""

    def post(self, request, record_id: int):
        record = get_object_or_404(
            PlayerDisciplinaryRecord.objects.select_related('league', 'player'),
            id=record_id
        )
        self.league = record.league
        if not self.test_func():
            return self.handle_no_permission()

        notes = request.POST.get('reinstatement_notes', '').strip()
        discipline_service.reinstate_player_penalty(record, notes, request.user)
        messages.success(request, f"✓ Lifted suspension for {record.player.display_name}. Player is reinstated.")
        return redirect('manage_disciplinary_hub', league_id=record.league.id)


class ReportGameIncidentView(LoginRequiredMixin, View):
    """Allows assigned official, umpire, or coach to report game conduct or ejections."""

    def post(self, request, game_id: int):
        game = get_object_or_404(Game.objects.select_related('season__league', 'team1', 'team2'), id=game_id)
        if not request.user.can_score_game(game):
            messages.error(request, "Permission denied to report incident for this game.")
            return redirect('game_detail', game_id=game.id)

        player_id = request.POST.get('player_id')
        player = get_object_or_404(CustomUser, id=player_id)
        incident_type = request.POST.get('incident_type', 'misconduct')
        description = request.POST.get('description', '').strip()
        is_ejection = bool(request.POST.get('is_ejection'))

        rec, msg = discipline_service.record_incident_report(
            game=game,
            player=player,
            reporting_user=request.user,
            incident_type=incident_type,
            description=description,
            is_ejection=is_ejection
        )

        if is_ejection:
            messages.warning(request, msg)
        else:
            messages.info(request, msg)

        return redirect('game_detail', game_id=game.id)


class SubmitSportsmanshipRatingView(LoginRequiredMixin, View):
    """Submits 1-5 star fellowship, referee respect, and bench decorum scores for a team."""

    def post(self, request, game_id: int):
        game = get_object_or_404(Game.objects.select_related('season__league', 'team1', 'team2'), id=game_id)
        rated_team_id = request.POST.get('rated_team_id')
        rated_team = get_object_or_404(Team, id=rated_team_id)

        is_official = (
            request.user.role == 'referee' or
            (hasattr(game, 'official_assignments') and game.official_assignments.filter(official=request.user).exists())
        )
        is_commish = request.user.is_overall_commissioner or (game.season and request.user.can_manage_league(game.season.league))
        is_coach = (game.team1.captain_id == request.user.id or game.team2.captain_id == request.user.id)

        if not (is_official or is_commish or is_coach):
            messages.error(request, "Permission denied to evaluate sportsmanship for this match.")
            return redirect('game_detail', game_id=game.id)

        try:
            score = int(request.POST.get('score', 5))
            respect = int(request.POST.get('respect_for_officials', 5))
            bench = int(request.POST.get('bench_conduct', 5))
        except (ValueError, TypeError):
            score, respect, bench = 5, 5, 5

        notes = request.POST.get('notes', '').strip()

        discipline_service.record_sportsmanship_rating(
            game=game,
            rated_team=rated_team,
            evaluator=request.user,
            score=score,
            respect_for_officials=respect,
            bench_conduct=bench,
            notes=notes
        )

        messages.success(request, f"✓ Thank you! Sportsmanship rating ({score}★) recorded for {rated_team.name}.")
        return redirect('game_detail', game_id=game.id)


class ManageSportsmanshipDashboardView(LeagueAdminRequiredMixin, View):
    """League Committee dashboard reviewing team fellowship scores and customizable renewal thresholds."""

    def get(self, request, league_id: int):
        league = self.get_league()
        teams_summary = discipline_service.get_league_sportsmanship_rankings(league)
        return render(request, 'leagues/sportsmanship_dashboard.html', {
            'league': league,
            'teams_summary': teams_summary,
        })

    def post(self, request, league_id: int):
        league = self.get_league()
        if 'update_thresholds' in request.POST:
            try:
                good_val = float(request.POST.get('sportsmanship_good_threshold', 4.0))
                rev_val = float(request.POST.get('sportsmanship_review_threshold', 3.0))
                league.sportsmanship_good_threshold = good_val
                league.sportsmanship_review_threshold = rev_val
                league.save(update_fields=['sportsmanship_good_threshold', 'sportsmanship_review_threshold'])
                messages.success(request, f"✓ Updated league sportsmanship thresholds: Good Standing >= {good_val:.2f}, Review >= {rev_val:.2f}.")
            except (ValueError, TypeError):
                messages.error(request, "Invalid threshold values entered.")

        return redirect('manage_sportsmanship_dashboard', league_id=league.id)
