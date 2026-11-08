"""
Views for Score Confirmations, Disputes, Commissioner Rulings, Bulk Finalizations, and Forfeits.
"""

from __future__ import annotations
from typing import Any
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import View
from leagues.models import Game
from leagues.forms import ScoreDisputeForm, ScoreResolutionForm, ForfeitForm
from core.services.notifications import send_discord_notification


class ConfirmGameScoreView(LoginRequiredMixin, View):
    """1-Tap score confirmation by the opposing coach, referee, or commissioner."""

    def post(self, request, game_id: int):
        game = get_object_or_404(
            Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'score_submitted_by'),
            id=game_id
        )
        if not request.user.can_score_game(game):
            messages.error(request, "Permission denied: you cannot verify scores for this match.")
            return redirect('game_detail', game_id=game.id)

        is_commish = request.user.is_overall_commissioner or (game.season and game.season.league and request.user.can_manage_league(game.season.league))
        assigned_official_ids = game.get_assigned_official_user_ids()
        is_assigned_official = request.user.id in assigned_official_ids

        # The user submitting the score cannot confirm their own score unless they are commissioner or assigned official
        if game.score_submitted_by == request.user and not (is_commish or is_assigned_official):
            messages.error(request, "Self-confirmation is not permitted. The opposing coach or an assigned official must verify the score.")
            return redirect('game_detail', game_id=game.id)

        if game.status not in ['pending_confirmation', 'disputed']:
            messages.info(request, f"Game score is already marked as {game.get_status_display()}.")
            return redirect('game_detail', game_id=game.id)

        game.confirm_score(request.user)
        messages.success(
            request,
            f"✓ Score confirmed! {game.team1.name} {game.team1_score} - {game.team2_score} {game.team2.name} is now official and recorded in standings."
        )
        return redirect('game_detail', game_id=game.id)


class DisputeGameScoreView(LoginRequiredMixin, View):
    """Opposing coach or team representative flags score discrepancy for commissioner review."""

    def post(self, request, game_id: int):
        game = get_object_or_404(
            Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'score_submitted_by'),
            id=game_id
        )
        if not request.user.can_score_game(game):
            messages.error(request, "Permission denied: you cannot dispute scores for this match.")
            return redirect('game_detail', game_id=game.id)

        assigned_official_ids = game.get_assigned_official_user_ids()
        is_commish = request.user.is_overall_commissioner or (game.season and game.season.league and request.user.can_manage_league(game.season.league))
        if game.score_confirmed and game.score_submitted_by_id in assigned_official_ids and not is_commish:
            messages.error(request, "This game was finalized by an official referee. Please contact your league commissioner directly to submit an appeal.")
            return redirect('game_detail', game_id=game.id)

        notes = request.POST.get('dispute_notes', '').strip()
        team1_score_str = request.POST.get('team1_score')
        team2_score_str = request.POST.get('team2_score')

        t1 = int(team1_score_str) if (team1_score_str and team1_score_str.isdigit()) else None
        t2 = int(team2_score_str) if (team2_score_str and team2_score_str.isdigit()) else None

        if not notes:
            notes = "Opposing coach contested the submitted score."

        game.dispute_score(request.user, notes=notes, opposing_t1_score=t1, opposing_t2_score=t2)
        if game.season and game.season.league and game.season.league.discord_webhook_url:
            send_discord_notification(
                game.season.league.discord_webhook_url,
                f"⚠️ Score Disputed: {game.team1.name} vs {game.team2.name} ({game.season.league.name}). Disputed by {request.user.display_name}. Notes: {notes}"
            )
        messages.warning(
            request,
            "⚠️ Score marked as Disputed. The league commissioner has been notified to review and issue an official ruling."
        )
        return redirect('game_detail', game_id=game.id)


class ResolveScoreDisputeView(LoginRequiredMixin, View):
    """Commissioner-exclusive ruling resolving a disputed score."""

    def post(self, request, game_id: int):
        game = get_object_or_404(Game.objects.select_related('season__league', 'team1__church', 'team2__church'), id=game_id)
        is_commish = request.user.is_overall_commissioner or (game.season and game.season.league and request.user.can_manage_league(game.season.league))
        if not is_commish:
            messages.error(request, "Permission denied: Only League Commissioners can resolve score disputes.")
            return redirect('game_detail', game_id=game.id)

        try:
            t1_score = int(request.POST.get('team1_score', game.team1_score))
            t2_score = int(request.POST.get('team2_score', game.team2_score))
        except (ValueError, TypeError):
            messages.error(request, "Invalid score values provided.")
            return redirect('game_detail', game_id=game.id)

        notes = request.POST.get('resolution_notes', '').strip()
        game.team1_score = t1_score
        game.team2_score = t2_score
        game.status = 'completed'
        game.score_confirmed = True
        game.score_confirmed_by = request.user
        if notes:
            existing = f"{game.score_dispute_notes}\n" if game.score_dispute_notes else ""
            game.score_dispute_notes = f"{existing}[RESOLVED by {request.user.display_name}]: {notes}".strip()
        game.log_score_event(request.user, 'dispute_resolved', f"Commissioner resolved score to {t1_score}-{t2_score}. Notes: {notes or 'No notes'}")
        game.save(update_fields=['team1_score', 'team2_score', 'status', 'score_confirmed', 'score_confirmed_by', 'score_dispute_notes', 'score_audit_log'])

        messages.success(
            request,
            f"✓ Dispute resolved! Official final score set to {game.team1.name} {t1_score} - {t2_score} {game.team2.name}."
        )
        return redirect('game_detail', game_id=game.id)


class BulkConfirmPendingScoresView(LoginRequiredMixin, View):
    """Overall commissioner 1-tap approval of all pending scores."""

    def post(self, request):
        if not request.user.is_overall_commissioner:
            messages.error(request, "Only league commissioners can bulk confirm scores.")
            return redirect('home')

        pending_games = Game.objects.filter(status='pending_confirmation')
        count = 0
        for g in pending_games:
            g.confirm_score(request.user)
            count += 1

        messages.success(request, f"✓ Successfully confirmed {count} pending game score(s). All standings updated.")
        return redirect('home')


class RecordGameForfeitView(LoginRequiredMixin, View):
    """1-Tap Forfeit scoring assistant."""

    def post(self, request, game_id: int):
        game = get_object_or_404(Game.objects.select_related('season__league', 'team1', 'team2'), id=game_id)
        if not request.user.can_score_game(game):
            messages.error(request, "Permission denied: you cannot score this match.")
            return redirect('game_detail', game_id=game.id)

        forfeiting_team_id = request.POST.get('forfeiting_team_id')
        if str(forfeiting_team_id) == str(game.team1.id):
            forfeiting_team = game.team1
        elif str(forfeiting_team_id) == str(game.team2.id):
            forfeiting_team = game.team2
        else:
            messages.error(request, "Invalid forfeiting team specified.")
            return redirect('game_detail', game_id=game.id)

        game.record_forfeit(forfeiting_team, request.user)
        messages.success(
            request,
            f"✓ Forfeit recorded. {forfeiting_team.name} forfeited. Final score recorded: {game.team1.name} {game.team1_score} - {game.team2_score} {game.team2.name}."
        )
        return redirect('game_detail', game_id=game.id)
