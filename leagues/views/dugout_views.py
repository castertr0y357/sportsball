"""
Views for Live Dugout Console, Action processing API, Batch offline sync,
Live game state polling, Public GameCast, and Practice Sandbox.
"""

from __future__ import annotations
import json
from typing import Any
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import View, TemplateView
from leagues.models import Game, League
from leagues.views.mixins import ScorekeeperAccessMixin, JsonResponseMixin
from leagues.services import scoring_engine


class DugoutConsoleView(ScorekeeperAccessMixin, View):
    """Single-Operator Live Dugout Console with 1-tap scoreboard, lineup check-in & auto walk-up music."""

    def get(self, request, game_id: int):
        game = self.get_game()
        game.ensure_lineups_initialized()
        if not game.current_batter:
            game.advance_to_next_batter()
            game.save(update_fields=['current_batter', 'team1_batter_index', 'team2_batter_index'])

        is_locked = game.is_scorer_locked(request.user)
        if not is_locked:
            game.acquire_scorer_lock(request.user)
            game.save(update_fields=['active_scorer', 'active_scorer_expires_at'])

        state = scoring_engine.serialize_game_state(game)
        state['is_locked'] = is_locked
        return render(request, 'leagues/dugout_console.html', {
            'game': game,
            'initial_state_json': json.dumps(state),
            'is_locked': is_locked,
            'active_scorer': game.active_scorer,
        })


class DugoutActionView(LoginRequiredMixin, JsonResponseMixin, View):
    """AJAX endpoint for 1-tap Dugout Console actions with 10-state undo stack."""

    def post(self, request, game_id: int):
        game = get_object_or_404(
            Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'current_batter', 'active_scorer'),
            id=game_id
        )
        if not request.user.can_score_game(game):
            return self.json_error('Permission denied: you cannot score this match', status=403)

        if game.status in ['completed', 'disputed'] or game.score_confirmed:
            return JsonResponse({
                'status': 'already_finalized',
                'error': 'This game was already marked final or disputed online. Stale offline actions were not applied.',
                'is_locked': True,
            }, status=409)

        try:
            payload = json.loads(request.body.decode('utf-8')) if request.body else request.POST
        except json.JSONDecodeError:
            payload = request.POST

        action = payload.get('action', '')

        if action == 'take_over_scoring':
            game.acquire_scorer_lock(request.user)
            game.log_score_event(request.user, 'scorer_takeover', f"Scorekeeping taken over by {request.user.display_name}")
            game.save(update_fields=['active_scorer', 'active_scorer_expires_at', 'score_audit_log'])
            state = scoring_engine.serialize_game_state(game)
            state['is_locked'] = False
            return JsonResponse(state)

        if game.is_scorer_locked(request.user):
            scorer_name = game.active_scorer.display_name if game.active_scorer else "another scorekeeper"
            return JsonResponse({
                'error': f"Game scoring is currently active by {scorer_name}. You are in view-only mode.",
                'locked': True,
                'active_scorer': scorer_name,
                'active_scorer_id': game.active_scorer_id,
            }, status=423)

        game.acquire_scorer_lock(request.user)

        if action == 'undo':
            success = game.pop_snapshot()
            if success:
                game.log_score_event(request.user, 'undo_play', f"Undone last action by {request.user.display_name}")
                game.save()
            state = scoring_engine.serialize_game_state(game)
            state['trigger_walkup'] = False
            state['is_locked'] = False
            state['undone'] = success
            return JsonResponse(state)

        # Mutating action
        if action == 'mark_final':
            game.push_snapshot()
            game.submit_score(request.user)
            game.log_play(f"FINAL SCORE: {game.team1.name} {game.team1_score}, {game.team2.name} {game.team2_score}")
            game.save()
            state = scoring_engine.serialize_game_state(game)
            state['trigger_walkup'] = False
            state['is_locked'] = False
            return JsonResponse(state)

        trigger_walkup, state = scoring_engine.apply_scoring_action(game, action, payload)
        state['trigger_walkup'] = trigger_walkup
        state['is_locked'] = False
        return JsonResponse(state)


class DugoutBatchSyncView(LoginRequiredMixin, JsonResponseMixin, View):
    """Flush and sync offline queued actions in chronological order."""

    def post(self, request, game_id: int):
        game = get_object_or_404(
            Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'current_batter'),
            id=game_id
        )
        if not request.user.can_score_game(game):
            return self.json_error('Permission denied: you cannot score this match', status=403)

        if game.status in ['completed', 'disputed'] or game.score_confirmed:
            return JsonResponse({
                'status': 'already_finalized',
                'error': 'This game was already marked final or disputed online. Stale offline actions were not applied.',
                'is_locked': True,
            }, status=409)

        try:
            data = json.loads(request.body.decode('utf-8'))
            actions = data.get('actions', [])
        except Exception as e:
            return self.json_error(str(e), status=400)

        applied_count = 0
        for item in actions:
            act = item.get('action')
            if act:
                scoring_engine.apply_dugout_action_internal(game, act, item)
                applied_count += 1

        game.save()
        state = scoring_engine.serialize_game_state(game)
        state['synced_count'] = applied_count
        return JsonResponse(state)


class GameLiveStateView(View):
    """Public JSON endpoint polled by the Live GameCast view."""

    def get(self, request, game_id: int):
        game = get_object_or_404(
            Game.objects.select_related('season__league', 'team1', 'team2', 'current_batter'),
            id=game_id
        )
        return JsonResponse(scoring_engine.serialize_game_state(game))


class GamecastView(View):
    """Public mobile-friendly Live GameCast scoreboard & diamond view for parents and spectators."""

    def get(self, request, game_id: int):
        game = get_object_or_404(
            Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'current_batter'),
            id=game_id
        )
        game.ensure_lineups_initialized()
        state = scoring_engine.serialize_game_state(game)
        return render(request, 'leagues/gamecast.html', {
            'game': game,
            'initial_state_json': json.dumps(state),
        })


class PracticeSandboxView(LoginRequiredMixin, View):
    """Interactive practice sandbox allowing volunteers, coaches, and umpires to practice scoring."""

    def get(self, request):
        sport = request.GET.get('sport', 'softball')
        is_diamond = sport in ('softball', 'baseball')
        score_label = 'Runs' if is_diamond else ('Goals' if sport == 'soccer' else 'Points')
        period_label = 'Inning' if is_diamond else ('Quarter' if sport in ('basketball', 'flag_football') else 'Set')

        team1_name = "Grace Fellowship (Home)"
        team2_name = "Calvary Lions (Away)"

        team1_lineup = [
            {'entry_id': 101, 'order': 1, 'player_id': 1, 'name': 'Josh Peterson', 'jersey': 12, 'is_present': True, 'walkup_title': 'Awesome God (Brass Riff)'},
            {'entry_id': 102, 'order': 2, 'player_id': 2, 'name': 'Caleb Brooks', 'jersey': 34, 'is_present': True, 'walkup_title': 'Victory Fanfare'},
            {'entry_id': 103, 'order': 3, 'player_id': 3, 'name': 'Paul Andrews', 'jersey': 99, 'is_present': True, 'walkup_title': 'Organ Charge'},
            {'entry_id': 104, 'order': 4, 'player_id': 4, 'name': 'Mike Taylor', 'jersey': 8, 'is_present': True, 'walkup_title': 'Centerfield'},
        ]
        team2_lineup = [
            {'entry_id': 201, 'order': 1, 'player_id': 11, 'name': 'Micah Thompson', 'jersey': 3, 'is_present': True, 'walkup_title': 'Strike Up the Band'},
            {'entry_id': 202, 'order': 2, 'player_id': 12, 'name': 'David Miller', 'jersey': 23, 'is_present': True, 'walkup_title': 'Eye of the Tiger'},
            {'entry_id': 203, 'order': 3, 'player_id': 13, 'name': 'Sam Wilson', 'jersey': 17, 'is_present': True, 'walkup_title': 'Grand Slam'},
            {'entry_id': 204, 'order': 4, 'player_id': 14, 'name': 'Luke Vance', 'jersey': 11, 'is_present': True, 'walkup_title': 'Chariots of Fire'},
        ]

        initial_state = {
            'game_id': 99999,
            'status': 'practice',
            'status_display': 'Practice Sandbox Mode',
            'team1_name': team1_name,
            'team2_name': team2_name,
            'team1_score': 0,
            'team2_score': 0,
            'team1_hits': 0,
            'team2_hits': 0,
            'current_inning': 1,
            'inning_half': 'top',
            'inning_half_display': 'Top',
            'batting_team_name': team2_name,
            'outs': 0,
            'runner_on_first': False,
            'runner_on_second': False,
            'runner_on_third': False,
            'current_batter': {
                'id': 11,
                'name': 'Micah Thompson',
                'jersey_number': 3,
                'walkup_song_title': 'Strike Up the Band',
                'walkup_song_url': '',
                'walkup_start_seconds': 0,
                'walkup_duration_seconds': 8,
            },
            'on_deck_batter': {
                'id': 12,
                'name': 'David Miller',
                'jersey_number': 23,
                'walkup_song_title': 'Eye of the Tiger',
                'walkup_song_url': '',
                'walkup_start_seconds': 0,
                'walkup_duration_seconds': 8,
            },
            'play_by_play': [
                "Welcome to the Practice Sandbox! None of your taps here will affect official league standings or records."
            ],
            'team1_lineup': team1_lineup,
            'team2_lineup': team2_lineup,
            'is_diamond_sport': is_diamond,
            'score_label': score_label,
            'period_label': period_label,
            'sport': sport,
            'enable_game_clock': sport in ('basketball', 'flag_football', 'soccer'),
            'default_period_minutes': 20 if sport in ('basketball', 'flag_football') else 45,
            'enable_flag_football_clocks': (sport == 'flag_football'),
            'enable_time_limit_clock': (sport in ('softball', 'baseball')),
            'enable_timeout_clock': True,
            'clock_seconds_remaining': 1200,
            'clock_running': False,
        }

        return render(request, 'leagues/practice_sandbox.html', {
            'initial_state_json': json.dumps(initial_state),
            'selected_sport': sport,
            'sports': League.SPORT_CHOICES,
        })


class TakeOverDugoutScoringView(LoginRequiredMixin, View):
    """Allows an authorized coach, referee, or commissioner to take over scoring lock."""

    def post(self, request, game_id: int):
        return self._takeover(request, game_id)

    def get(self, request, game_id: int):
        return self._takeover(request, game_id)

    def _takeover(self, request, game_id: int):
        game = get_object_or_404(
            Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'active_scorer'),
            id=game_id
        )
        if not request.user.can_score_game(game):
            messages.error(request, "Permission denied: you cannot score this match.")
            return redirect('gamecast', game_id=game.id)

        game.acquire_scorer_lock(request.user)
        game.log_score_event(request.user, 'scorer_takeover', f"Scorekeeping control taken over by {request.user.display_name}")
        game.save(update_fields=['active_scorer', 'active_scorer_expires_at', 'score_audit_log'])

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({'status': 'ok', 'active_scorer': request.user.display_name, 'is_locked': False})

        messages.success(request, "Scorekeeping lock acquired. You are now the active scorer for this game.")
        return redirect('dugout_console', game_id=game.id)
