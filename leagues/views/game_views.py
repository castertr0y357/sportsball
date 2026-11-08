"""
Views for Game detail, manual score/stat entry, player attendance RSVP,
and interactive lineup & rotation builder.
"""

from __future__ import annotations
import json
from typing import Any
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Max, Q
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import View, DetailView
from leagues.models import Game, Team, GameLineupEntry, GameRSVP
from leagues.forms import GameScoreForm
from stats.models import PlayerGameStat, SPORT_DEFAULT_CATEGORIES
from stats.forms import PlayerGameStatForm
from core.services.notifications import send_discord_notification
from leagues.services.calendar_feed import generate_ics_feed
from users.models import CustomUser


class GameDetailView(DetailView):
    """Detailed game overview with live score status, RSVP dashboard, and player stats."""
    model = Game
    pk_url_kwarg = 'game_id'
    template_name = 'leagues/game_detail.html'
    context_object_name = 'game'

    def get_queryset(self):
        return Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'current_batter')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        game = self.object
        player_stats = game.player_stats.select_related('player', 'team').all()
        sport = game.season.league.sport if game.season_id else 'basketball'
        suggested_categories = [name for name, _abbr in SPORT_DEFAULT_CATEGORIES.get(sport, SPORT_DEFAULT_CATEGORIES['other'])]

        user = self.request.user
        can_score = user.is_authenticated and user.can_score_game(game)
        score_form = GameScoreForm(instance=game) if can_score else None
        stat_form = PlayerGameStatForm(game=game) if can_score else None

        user_rsvp = None
        is_rostered = False
        user_team = None
        can_manage_team1_lineup = False
        can_manage_team2_lineup = False

        if user.is_authenticated:
            user_rsvp = game.get_player_rsvp(user)
            if game.team1.players.filter(id=user.id).exists():
                is_rostered = True
                user_team = game.team1
            elif game.team2.players.filter(id=user.id).exists():
                is_rostered = True
                user_team = game.team2

            can_manage_team1_lineup = (
                user == game.team1.captain or
                user.can_manage_church(game.team1.church) or
                user.can_manage_league(game.season.league) or
                user.is_overall_commissioner
            )
            can_manage_team2_lineup = (
                user == game.team2.captain or
                user.can_manage_church(game.team2.church) or
                user.can_manage_league(game.season.league) or
                user.is_overall_commissioner
            )

        team1_rsvp_summary = game.get_team_rsvp_summary(game.team1)
        team2_rsvp_summary = game.get_team_rsvp_summary(game.team2)

        is_commish = user.is_authenticated and (
            user.is_overall_commissioner or (game.season and game.season.league and user.can_manage_league(game.season.league))
        )
        assigned_official_ids = game.get_assigned_official_user_ids()
        is_assigned_official = user.is_authenticated and (user.id in assigned_official_ids)
        official_score_locked = (
            game.score_confirmed and
            game.score_submitted_by_id in assigned_official_ids and
            not (is_commish or is_assigned_official)
        )

        can_confirm_score = False
        can_dispute_score = False
        if user.is_authenticated and can_score and game.status == 'pending_confirmation':
            if is_commish or user != game.score_submitted_by:
                can_confirm_score = True
                can_dispute_score = True

        context.update({
            'player_stats': player_stats,
            'score_form': score_form,
            'stat_form': stat_form,
            'suggested_categories': suggested_categories,
            'can_score': can_score,
            'user_rsvp': user_rsvp,
            'is_rostered': is_rostered,
            'user_team': user_team,
            'can_manage_team1_lineup': can_manage_team1_lineup,
            'can_manage_team2_lineup': can_manage_team2_lineup,
            'team1_rsvp_summary': team1_rsvp_summary,
            'team2_rsvp_summary': team2_rsvp_summary,
            'can_confirm_score': can_confirm_score,
            'can_dispute_score': can_dispute_score,
            'is_commissioner': is_commish,
            'official_score_locked': official_score_locked,
        })
        return context


class RecordGameScoreView(LoginRequiredMixin, View):
    """Submits or updates final scores and moves game into pending_confirmation or completed."""

    def get(self, request, game_id: int):
        return redirect('game_detail', game_id=game_id)

    def post(self, request, game_id: int):
        game = get_object_or_404(Game.objects.select_related('season__league', 'team1__church', 'team2__church'), id=game_id)
        if not request.user.can_score_game(game):
            messages.error(request, "You do not have permission to record game scores for this match.")
            return redirect('game_detail', game_id=game.id)

        assigned_official_ids = game.get_assigned_official_user_ids()
        is_assigned_official = request.user.id in assigned_official_ids
        is_commish = request.user.is_overall_commissioner or (game.season and game.season.league and request.user.can_manage_league(game.season.league))

        if game.score_confirmed and game.score_submitted_by_id in assigned_official_ids and not (is_assigned_official or is_commish):
            messages.error(request, "This game was finalized by the official referee. To request a correction, please contact your league commissioner.")
            return redirect('game_detail', game_id=game.id)

        form = GameScoreForm(request.POST, instance=game)
        if form.is_valid():
            new_status = form.cleaned_data.get('status')
            t1_score = form.cleaned_data.get('team1_score', 0)
            t2_score = form.cleaned_data.get('team2_score', 0)

            if new_status == 'completed':
                game.submit_score(request.user, t1_score, t2_score)
                game.notes = form.cleaned_data.get('notes', game.notes)
                game.save()

                if game.status == 'completed':
                    messages.success(
                        request,
                        f"✓ Official score verified: {game.team1.name} {game.team1_score} - {game.team2_score} {game.team2.name}."
                    )
                else:
                    messages.info(
                        request,
                        f"Reported score: {game.team1.name} {game.team1_score} - {game.team2_score} {game.team2.name}. Sent to opposing coach for 1-tap confirmation."
                    )
                    if game.season and game.season.league and game.season.league.discord_webhook_url:
                        send_discord_notification(
                            game.season.league.discord_webhook_url,
                            f"📋 Score Reported: {game.team1.name} {game.team1_score} - {game.team2_score} {game.team2.name} ({game.season.league.name}). Awaiting opponent confirmation."
                        )
            else:
                updated_game = form.save()
                messages.success(
                    request,
                    f"Updated game: {updated_game.team1.name} vs {updated_game.team2.name} ({updated_game.get_status_display()})"
                )

        return redirect('game_detail', game_id=game.id)


class AddGameStatView(LoginRequiredMixin, View):
    """Adds individual player stats (e.g. Hits, Goals, Points, Fouls)."""

    def post(self, request, game_id: int):
        game = get_object_or_404(Game.objects.select_related('season__league', 'team1__church', 'team2__church'), id=game_id)
        if not request.user.can_score_game(game):
            messages.error(request, "You do not have permission to record player stats for this match.")
            return redirect('game_detail', game_id=game.id)

        form = PlayerGameStatForm(request.POST, game=game)
        if form.is_valid():
            player = form.cleaned_data['player']
            team = form.cleaned_data['team']
            category = form.cleaned_data['category']
            value = form.cleaned_data['value']
            if not team:
                if game.team1.players.filter(id=player.id).exists():
                    team = game.team1
                elif game.team2.players.filter(id=player.id).exists():
                    team = game.team2

            PlayerGameStat.objects.update_or_create(
                player=player,
                game=game,
                category=category,
                defaults={'team': team, 'value': value}
            )
            messages.success(request, f"Recorded {category}: {value} for {player.display_name}.")

        return redirect('game_detail', game_id=game.id)


class GameRSVPView(LoginRequiredMixin, View):
    """1-Tap Attendance RSVP endpoint for players on team rosters."""

    def post(self, request, game_id: int):
        game = get_object_or_404(Game.objects.select_related('team1', 'team2', 'season'), id=game_id)
        user = request.user

        team = None
        if game.team1.players.filter(id=user.id).exists():
            team = game.team1
        elif game.team2.players.filter(id=user.id).exists():
            team = game.team2
        else:
            if not (user.is_overall_commissioner or user.can_manage_church(game.team1.church) or user.can_manage_church(game.team2.church)):
                return JsonResponse({'error': 'You are not on the roster for either team in this game.'}, status=403)

        try:
            payload = json.loads(request.body.decode('utf-8')) if request.body else request.POST
        except json.JSONDecodeError:
            payload = request.POST

        response_val = str(payload.get('response', '')).strip().lower()
        if response_val not in ('yes', 'no', 'maybe'):
            return JsonResponse({'error': 'Invalid response (must be yes, no, or maybe)'}, status=400)

        notes = str(payload.get('notes', '')).strip()[:150]

        rsvp, _created = GameRSVP.objects.update_or_create(
            game=game,
            player=user,
            defaults={'response': response_val, 'notes': notes}
        )

        if team:
            entry = game.lineup_entries.filter(team=team, player=user).first()
            if entry:
                entry.is_present = (response_val != 'no')
                entry.save(update_fields=['is_present'])

        team_summary = game.get_team_rsvp_summary(team) if team else {}
        return JsonResponse({
            'success': True,
            'response': response_val,
            'response_display': rsvp.get_response_display(),
            'team_summary': team_summary,
        })


class GameLineupBuilderView(LoginRequiredMixin, View):
    """Coaches' lineup builder, defensive rotation manager, and RSVP integration."""

    def get(self, request, game_id: int, team_id: int):
        res = self._get_game_and_team(request, game_id, team_id)
        if isinstance(res, HttpResponse):
            return res
        game, team = res
        context = self._build_context(game, team)
        return render(request, 'leagues/lineup_builder.html', context)

    def post(self, request, game_id: int, team_id: int):
        res = self._get_game_and_team(request, game_id, team_id)
        if isinstance(res, HttpResponse):
            return res
        game, team = res
        action = request.POST.get('action', 'save_lineup')
        sport, available_positions, periods = self._get_sport_configuration(game)

        if action == 'autofill_rsvps':
            rsvps = {r.player_id: r.response for r in game.rsvps.filter(player__in=team.players.all())}
            entries = list(game.lineup_entries.filter(team=team).select_related('player'))

            def sort_key(e):
                resp = rsvps.get(e.player_id, 'pending')
                if resp == 'yes':
                    return (0, e.batting_order)
                elif resp in ('maybe', 'pending'):
                    return (1, e.batting_order)
                else:
                    return (2, e.batting_order)

            entries.sort(key=sort_key)
            for new_idx, entry in enumerate(entries, start=1):
                resp = rsvps.get(entry.player_id, 'pending')
                entry.batting_order = new_idx
                entry.is_present = (resp != 'no')
                entry.save(update_fields=['batting_order', 'is_present'])

            messages.success(request, f"⚡ Lineup auto-sorted for {team.name} based on confirmed player RSVPs!")

        elif action == 'copy_previous_lineup':
            prev_game = Game.objects.filter(
                Q(team1=team) | Q(team2=team),
                season=game.season
            ).exclude(id=game.id).filter(date__lt=game.date).order_by('-date').first()
            if not prev_game:
                prev_game = Game.objects.filter(
                    Q(team1=team) | Q(team2=team),
                    season=game.season
                ).exclude(id=game.id).order_by('-date').first()

            if prev_game:
                prev_entries = {e.player_id: e for e in prev_game.lineup_entries.filter(team=team)}
                current_entries = list(game.lineup_entries.filter(team=team))
                copied_count = 0
                for ce in current_entries:
                    if ce.player_id in prev_entries:
                        pe = prev_entries[ce.player_id]
                        ce.batting_order = pe.batting_order
                        ce.field_position = pe.field_position
                        ce.position_rotations = pe.position_rotations
                        ce.is_present = pe.is_present
                        ce.save(update_fields=['batting_order', 'field_position', 'position_rotations', 'is_present'])
                        copied_count += 1
                messages.success(request, f"⚡ Copied lineup & rotations from game on {prev_game.date.strftime('%b %d')} for {copied_count} players!")
            else:
                messages.warning(request, "No previous game found to copy lineup from.")

        elif action == 'save_as_default':
            current_entries = list(game.lineup_entries.filter(team=team).select_related('player'))
            template_data = []
            for e in current_entries:
                template_data.append({
                    'player_id': e.player_id,
                    'batting_order': e.batting_order,
                    'field_position': e.field_position,
                    'position_rotations': e.position_rotations,
                    'is_present': e.is_present,
                })
            team.default_lineup = {'entries': template_data}
            team.save(update_fields=['default_lineup'])
            messages.success(request, f"💾 Saved current lineup as the Master Depth Chart / Template for {team.name}!")

        elif action == 'load_default_lineup':
            if team.default_lineup and 'entries' in team.default_lineup:
                template_map = {item['player_id']: item for item in team.default_lineup['entries']}
                current_entries = list(game.lineup_entries.filter(team=team))
                applied = 0
                for ce in current_entries:
                    if ce.player_id in template_map:
                        item = template_map[ce.player_id]
                        ce.batting_order = item.get('batting_order', ce.batting_order)
                        ce.field_position = item.get('field_position', ce.field_position)
                        ce.position_rotations = item.get('position_rotations', ce.position_rotations)
                        ce.is_present = item.get('is_present', True)
                        ce.save(update_fields=['batting_order', 'field_position', 'position_rotations', 'is_present'])
                        applied += 1
                messages.success(request, f"Applied Master Lineup Template for {applied} players!")
            else:
                messages.warning(request, "No Master Lineup Template has been saved yet.")

        elif action == 'add_emergency_sub':
            league_obj = game.season.league if (game.season and game.season.league) else None
            if not (league_obj and league_obj.allow_emergency_subs):
                messages.error(request, "Emergency substitutes are not permitted in this league.")
            elif game.game_type != 'regular':
                messages.error(request, "Emergency substitutes are strictly prohibited in playoff tournament games.")
            else:
                sub_user_id = request.POST.get('sub_user_id')
                consent_confirmed = bool(request.POST.get('consent_confirmed'))
                if not consent_confirmed:
                    messages.warning(request, "You must certify that the opposing team's coach agreed to this emergency pickup player.")
                else:
                    sub_player = get_object_or_404(CustomUser, id=sub_user_id)
                    if not game.lineup_entries.filter(team=team, player=sub_player).exists():
                        max_order = game.lineup_entries.filter(team=team).aggregate(Max('batting_order'))['batting_order__max'] or 0
                        GameLineupEntry.objects.create(
                            game=game,
                            team=team,
                            player=sub_player,
                            batting_order=max_order + 1,
                            field_position='EH',
                            is_present=True,
                            is_emergency_sub=True,
                            sub_consented_by_opponent=True
                        )
                        messages.success(request, f"Added emergency substitute {sub_player.display_name} with opposing coach consent.")

        elif action == 'save_lineup':
            entries = list(game.lineup_entries.filter(team=team).select_related('player'))
            league_obj = game.season.league if (game.season and game.season.league) else None
            for entry in entries:
                order_val = request.POST.get(f'order_{entry.id}')
                pos_val = request.POST.get(f'position_{entry.id}', '').strip()
                present_val = bool(request.POST.get(f'present_{entry.id}'))

                rotations = {}
                for period_idx in range(1, len(periods) + 1):
                    p_val = request.POST.get(f'rotation_{entry.id}_{period_idx}', '').strip()
                    if p_val:
                        rotations[str(period_idx)] = p_val

                if order_val and order_val.isdigit():
                    entry.batting_order = int(order_val)
                entry.field_position = pos_val
                entry.position_rotations = rotations
                eligible, _ = entry.player.is_eligible_to_play(league_obj)
                entry.is_present = (present_val and eligible)
                entry.save(update_fields=['batting_order', 'field_position', 'position_rotations', 'is_present'])

            messages.success(request, f"Saved batting order and defensive rotations for {team.name}!")

        return redirect('game_lineup_builder', game_id=game.id, team_id=team.id)

    def _get_game_and_team(self, request, game_id, team_id):
        game = get_object_or_404(Game.objects.select_related('season__league', 'team1__church', 'team2__church'), id=game_id)
        team = get_object_or_404(Team.objects.select_related('church', 'captain', 'season__league'), id=team_id)
        if team not in (game.team1, game.team2):
            messages.error(request, f"{team.name} is not participating in this game.")
            return redirect('game_detail', game_id=game.id)
        if not request.user.can_manage_team(team):
            messages.error(request, f"You do not have permission to manage the lineup for {team.name}.")
            return redirect('game_detail', game_id=game.id)
        game.ensure_lineups_initialized()
        return game, team

    def _get_sport_configuration(self, game):
        sport = game.season.league.sport if (game.season and game.season.league) else 'softball'
        if sport in ('softball', 'baseball'):
            available_positions = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'Rover', 'EH', 'Bench']
            periods = [f"Inning {i}" for i in range(1, 8)]
        elif sport == 'basketball':
            available_positions = ['PG', 'SG', 'SF', 'PF', 'C', '6th Man', 'Bench']
            periods = [f"Quarter {i}" for i in range(1, 5)]
        elif sport in ('flag_football', 'soccer'):
            available_positions = ['QB', 'WR', 'RB', 'C', 'DB', 'LB', 'Bench'] if sport == 'flag_football' else ['FWD', 'MID', 'DEF', 'GK', 'Bench']
            periods = ['1st Half', '2nd Half']
        else:
            available_positions = ['Pos 1', 'Pos 2', 'Pos 3', 'Pos 4', 'Pos 5', 'Bench']
            periods = ['Set 1', 'Set 2', 'Set 3']
        return sport, available_positions, periods

    def _build_context(self, game, team):
        sport, available_positions, periods = self._get_sport_configuration(game)
        entries = list(game.lineup_entries.filter(team=team).select_related('player').order_by('batting_order', 'id'))
        rsvps = {r.player_id: r for r in game.rsvps.filter(player__in=team.players.all())}
        is_playoff = (game.game_type == 'playoff')
        league_obj = game.season.league if (game.season and game.season.league) else None

        for e in entries:
            e.rsvp = rsvps.get(e.player_id)
            e.rotation_dict = e.position_rotations or {}
            eligible, inelig_reason = e.player.is_eligible_to_play(league_obj)
            e.is_eligible = eligible
            e.ineligibility_reason = inelig_reason
            if not eligible:
                e.is_present = False
            if is_playoff:
                reg_appearances = GameLineupEntry.objects.filter(
                    player_id=e.player_id,
                    game__season=game.season,
                    game__game_type='regular',
                    is_present=True
                ).count()
                e.reg_appearances = reg_appearances
                e.is_playoff_eligible = (reg_appearances >= 2)
            else:
                e.reg_appearances = 0
                e.is_playoff_eligible = True

        present_entries = [e for e in entries if e.is_present]
        consecutive_male_pairs = []
        male_count = sum(1 for e in present_entries if getattr(e.player, 'gender', '') == 'M')
        female_count = sum(1 for e in present_entries if getattr(e.player, 'gender', '') == 'F')

        for i in range(len(present_entries) - 1):
            g1 = getattr(present_entries[i].player, 'gender', '')
            g2 = getattr(present_entries[i+1].player, 'gender', '')
            if g1 == 'M' and g2 == 'M':
                consecutive_male_pairs.append((present_entries[i].batting_order, present_entries[i+1].batting_order))

        coed_status = {
            'male_count': male_count,
            'female_count': female_count,
            'has_gender_data': bool(male_count or female_count),
            'is_alternating': len(consecutive_male_pairs) == 0,
            'consecutive_male_pairs': consecutive_male_pairs,
        }

        num_periods = len(periods)
        for e in entries:
            rotations = e.position_rotations or {}
            fielding_innings = 0
            bench_innings = 0
            if not e.is_present:
                bench_innings = num_periods
            else:
                if rotations:
                    for p_idx in range(1, num_periods + 1):
                        pos = rotations.get(str(p_idx), e.field_position)
                        if pos in ('Bench', '-', '', None):
                            bench_innings += 1
                        else:
                            fielding_innings += 1
                else:
                    if e.field_position in ('Bench', '-', '', None):
                        bench_innings = num_periods
                    else:
                        fielding_innings = num_periods
            e.fielding_innings = fielding_innings
            e.bench_innings = bench_innings

        rsvp_summary = game.get_team_rsvp_summary(team)
        opponent = game.team2 if team == game.team1 else game.team1
        has_saved_default = bool(team.default_lineup and team.default_lineup.get('entries'))

        return {
            'game': game,
            'team': team,
            'opponent': opponent,
            'entries': entries,
            'available_positions': available_positions,
            'periods': periods,
            'rsvp_summary': rsvp_summary,
            'sport': sport,
            'coed_status': coed_status,
            'has_saved_default': has_saved_default,
            'is_playoff': is_playoff,
            'allow_emergency_subs': bool(league_obj and league_obj.allow_emergency_subs),
            'available_subs': (CustomUser.objects.filter(
                Q(church=team.church) | Q(is_sub_available=True) | Q(is_free_agent=True)
            ).exclude(id__in=[entry.player_id for entry in entries]).distinct()[:15]) if (league_obj and league_obj.allow_emergency_subs and not is_playoff) else [],
        }


class GameLineupPrintView(View):
    """Clean, print-optimized umpire and dugout lineup card (RFC/standard format)."""

    def get(self, request, game_id: int, team_id: int):
        game = get_object_or_404(
            Game.objects.select_related('season__league', 'team1__church', 'team2__church'),
            id=game_id
        )
        team = get_object_or_404(Team.objects.select_related('church', 'captain', 'season__league'), id=team_id)
        if team not in (game.team1, game.team2):
            messages.error(request, f"{team.name} is not in this game.")
            return redirect('game_detail', game_id=game.id)

        game.ensure_lineups_initialized()
        opponent = game.team2 if team == game.team1 else game.team1

        entries = list(
            game.lineup_entries.filter(team=team)
            .select_related('player')
            .order_by('batting_order', 'id')
        )
        active_lineup = [e for e in entries if e.is_present]
        bench_substitutes = [e for e in entries if not e.is_present]

        sport = game.season.league.sport if (game.season and game.season.league) else 'softball'
        if sport in ('softball', 'baseball'):
            period_headers = [f"Inn {i}" for i in range(1, 8)]
        elif sport == 'basketball':
            period_headers = [f"Q{i}" for i in range(1, 5)]
        elif sport in ('flag_football', 'soccer'):
            period_headers = ['1st Half', '2nd Half']
        else:
            period_headers = ['Set 1', 'Set 2', 'Set 3']

        num_p = len(period_headers)
        for e in active_lineup:
            rot = e.position_rotations or {}
            e.rotation_dict = rot
            e.period_positions = [rot.get(str(i), e.field_position or '-') for i in range(1, num_p + 1)]

        return render(request, 'leagues/lineup_print.html', {
            'game': game,
            'team': team,
            'opponent': opponent,
            'active_lineup': active_lineup,
            'bench_substitutes': bench_substitutes,
            'period_headers': period_headers,
            'sport': sport,
        })


class UserCalendarIcsView(View):
    """Personalized iCalendar (.ics) feed of all scheduled games for the logged-in user."""

    def get(self, request):
        if not request.user.is_authenticated:
            return HttpResponseForbidden("Please log in to download your personalized schedule.")

        user_teams = Team.objects.filter(Q(players=request.user) | Q(captain=request.user)).distinct()
        games = Game.objects.filter(
            Q(team1__in=user_teams) | Q(team2__in=user_teams)
        ).select_related('team1', 'team2', 'season', 'season__league').distinct().order_by('date')

        cal_name = f"My SportsBall Games ({request.user.get_full_name() or request.user.username})"
        ics_body = generate_ics_feed(games, calendar_name=cal_name, request=request)
        filename = "my_church_sports_schedule.ics"

        response = HttpResponse(ics_body, content_type='text/calendar; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
