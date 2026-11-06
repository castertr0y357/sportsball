from datetime import timedelta
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import F
from .models import League, Season, Team, SeasonRegistration, Game, GameLineupEntry
from core.services.notifications import send_discord_notification, send_twilio_sms
from .forms import (
    LeagueForm, SeasonForm, TeamForm, SeasonRegistrationForm,
    GameForm, GameScoreForm, ScheduleGeneratorForm
)
from stats.models import PlayerGameStat, SPORT_DEFAULT_CATEGORIES
from stats.forms import PlayerGameStatForm


def league_list(request):
    leagues = League.objects.select_related('admin').prefetch_related('seasons').all()
    return render(request, 'leagues/league_list.html', {'leagues': leagues})


@login_required
def create_league(request):
    if not request.user.is_league_admin:
        messages.error(request, "You don't have permission to create leagues.")
        return redirect('league_list')
    if request.method == 'POST':
        form = LeagueForm(request.POST)
        if form.is_valid():
            league = form.save()
            messages.success(request, f"League '{league.name}' created successfully.")
            return redirect('league_list')
    else:
        form = LeagueForm(initial={'admin': request.user})
    return render(request, 'leagues/create_league.html', {'form': form})


def season_list(request, league_id):
    league = get_object_or_404(League, id=league_id)
    seasons = Season.objects.filter(league=league).prefetch_related('teams', 'games')
    return render(request, 'leagues/season_list.html', {'league': league, 'seasons': seasons})


@login_required
def create_season(request, league_id):
    league = get_object_or_404(League, id=league_id)
    if not request.user.is_league_admin:
        messages.error(request, "You don't have permission to create seasons.")
        return redirect('season_list', league_id=league_id)
    if request.method == 'POST':
        form = SeasonForm(request.POST)
        if form.is_valid():
            season = form.save(commit=False)
            season.league = league
            season.save()
            messages.success(request, f"Season '{season.name}' created successfully.")
            return redirect('season_list', league_id=league_id)
    else:
        form = SeasonForm()
    return render(request, 'leagues/create_season.html', {'form': form, 'league': league})


def season_detail(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    standings = season.get_standings()
    games = season.games.select_related('team1', 'team2').all()
    regular_games = [g for g in games if g.game_type == 'regular']
    playoff_games = [g for g in games if g.game_type != 'regular']
    registrations = season.registrations.select_related('player', 'preferred_team').all()
    user_registration = None
    if request.user.is_authenticated:
        user_registration = registrations.filter(player=request.user).first()

    return render(request, 'leagues/season_detail.html', {
        'season': season,
        'league': season.league,
        'standings': standings,
        'regular_games': regular_games,
        'playoff_games': playoff_games,
        'registrations': registrations,
        'user_registration': user_registration,
    })


def team_list(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    teams = Team.objects.filter(season=season).select_related('church', 'captain').prefetch_related('players')
    standings = season.get_standings()
    return render(request, 'leagues/team_list.html', {
        'season': season,
        'teams': teams,
        'standings': standings,
    })


@login_required
def create_team(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    if not request.user.can_manage_teams:
        messages.error(request, "You don't have permission to create teams.")
        return redirect('team_list', season_id=season_id)

    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save(commit=False)
            team.season = season
            team.league = season.league
            team.save()
            form.save_m2m()
            if team.captain and not team.players.filter(id=team.captain_id).exists():
                team.players.add(team.captain)
            messages.success(request, f"Team '{team.name}' created successfully.")
            return redirect('team_list', season_id=season_id)
    else:
        form = TeamForm(initial={'captain': request.user, 'church': request.user.church})
    return render(request, 'leagues/create_team.html', {'form': form, 'season': season})


def team_detail(request, team_id):
    team = get_object_or_404(
        Team.objects.select_related('league', 'season', 'church', 'captain').prefetch_related('players'),
        id=team_id
    )
    games = (
        Game.objects.filter(season=team.season)
        .filter(team1=team) | Game.objects.filter(season=team.season).filter(team2=team)
    ).select_related('team1', 'team2').order_by('date')
    pending_requests = team.registration_requests.filter(status='pending').select_related('player')
    is_captain_or_admin = (
        request.user.is_authenticated and (
            request.user == team.captain or
            request.user.is_league_admin or
            getattr(request.user, 'can_manage_teams', False)
        )
    )
    invite_url = team.get_invite_url(request)

    return render(request, 'leagues/team_detail.html', {
        'team': team,
        'games': games,
        'pending_requests': pending_requests,
        'is_captain_or_admin': is_captain_or_admin,
        'invite_url': invite_url,
    })


@login_required
def join_team(request, team_id):
    team = get_object_or_404(Team.objects.select_related('season'), id=team_id)
    if request.method == 'POST':
        if team.players.count() >= team.season.max_roster_size:
            messages.error(request, f"'{team.name}' has reached the maximum roster size ({team.season.max_roster_size}).")
            return redirect('team_detail', team_id=team.id)
        team.players.add(request.user)
        request.user.is_free_agent = False
        request.user.save(update_fields=['is_free_agent'])
        SeasonRegistration.objects.update_or_create(
            season=team.season,
            player=request.user,
            defaults={
                'preferred_team': team,
                'is_free_agent': False,
                'status': 'approved',
                'waiver_agreed': request.user.waiver_signed,
            }
        )
        messages.success(request, f"You have joined '{team.name}'!")
    return redirect('team_detail', team_id=team.id)


def join_team_by_invite(request, invite_code):
    team = get_object_or_404(
        Team.objects.select_related('league', 'season', 'church', 'captain').prefetch_related('players'),
        invite_code=invite_code
    )

    if not request.user.is_authenticated:
        from django.urls import reverse
        return redirect(f"{reverse('register')}?invite={invite_code}")

    if request.user in team.players.all():
        messages.info(request, f"You are already on the roster for {team.name}!")
        return redirect('team_detail', team_id=team.id)

    if request.method == 'POST':
        if team.players.count() >= team.season.max_roster_size:
            messages.error(request, f"'{team.name}' has reached the maximum roster size ({team.season.max_roster_size}).")
            return redirect('team_detail', team_id=team.id)

        team.players.add(request.user)
        request.user.is_free_agent = False
        request.user.save(update_fields=['is_free_agent'])
        SeasonRegistration.objects.update_or_create(
            season=team.season,
            player=request.user,
            defaults={
                'preferred_team': team,
                'is_free_agent': False,
                'status': 'approved',
                'waiver_agreed': request.user.waiver_signed,
            }
        )
        messages.success(request, f"You have joined {team.name}!")
        return redirect('team_detail', team_id=team.id)

    return render(request, 'leagues/join_team_confirm.html', {'team': team})



@login_required
def register_for_season(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    existing = SeasonRegistration.objects.filter(season=season, player=request.user).first()

    if request.method == 'POST':
        form = SeasonRegistrationForm(request.POST, instance=existing, season=season)
        if form.is_valid():
            reg = form.save(commit=False)
            reg.season = season
            reg.player = request.user
            if reg.is_free_agent or not reg.preferred_team:
                reg.is_free_agent = True
                request.user.is_free_agent = True
                request.user.save(update_fields=['is_free_agent'])
            if reg.waiver_agreed and not request.user.waiver_signed:
                request.user.sign_waiver(request.user.display_name)
            reg.save()
            messages.success(request, f"Registration submitted for {season.name}!")
            return redirect('season_detail', season_id=season.id)
    else:
        form = SeasonRegistrationForm(
            instance=existing,
            season=season,
            initial={'waiver_agreed': request.user.waiver_signed}
        )
    return render(request, 'leagues/season_register.html', {'form': form, 'season': season})


@login_required
def assign_registration(request, reg_id):
    reg = get_object_or_404(SeasonRegistration.objects.select_related('season', 'player', 'preferred_team'), id=reg_id)
    if not request.user.can_manage_teams:
        messages.error(request, "You do not have permission to approve registrations.")
        return redirect('season_detail', season_id=reg.season_id)

    if request.method == 'POST':
        team_id = request.POST.get('team_id')
        action = request.POST.get('action', 'approve')
        if action == 'toggle_dues':
            reg.dues_paid = not reg.dues_paid
            reg.save(update_fields=['dues_paid'])
            messages.success(request, f"Updated dues status for {reg.player.display_name}.")
        elif action == 'approve':
            target_team = get_object_or_404(Team, id=team_id, season=reg.season) if team_id else reg.preferred_team
            if target_team:
                target_team.players.add(reg.player)
                reg.preferred_team = target_team
                reg.status = 'approved'
                reg.is_free_agent = False
                reg.save()
                reg.player.is_free_agent = False
                reg.player.save(update_fields=['is_free_agent'])
                messages.success(request, f"{reg.player.display_name} assigned to {target_team.name}!")
            else:
                messages.error(request, "Please select a team to assign this player to.")
    return redirect('season_detail', season_id=reg.season_id)


@login_required
def create_game(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    if not request.user.can_manage_teams:
        messages.error(request, "You don't have permission to schedule games.")
        return redirect('season_detail', season_id=season.id)

    if request.method == 'POST':
        form = GameForm(request.POST, season=season)
        if form.is_valid():
            game = form.save(commit=False)
            game.season = season
            game.save()
            messages.success(request, f"Game scheduled: {game.team1.name} vs {game.team2.name}.")
            return redirect('season_detail', season_id=season.id)
    else:
        default_dt = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
        form = GameForm(
            season=season,
            initial={'date': default_dt.strftime('%Y-%m-%dT%H:%M'), 'location': 'Fellowship Hall Gym'}
        )
    return render(request, 'leagues/create_game.html', {'form': form, 'season': season})


@login_required
def generate_schedule(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    if not request.user.is_league_admin:
        messages.error(request, "Only league admins can auto-generate schedules.")
        return redirect('season_detail', season_id=season.id)

    teams = list(season.teams.all())
    if len(teams) < 2:
        messages.error(request, "At least 2 teams are required in the season to generate a schedule.")
        return redirect('season_detail', season_id=season.id)

    if request.method == 'POST':
        form = ScheduleGeneratorForm(request.POST)
        if form.is_valid():
            start_dt = form.cleaned_data['start_datetime']
            location = form.cleaned_data['location']
            double_rr = form.cleaned_data['double_round_robin']
            clear_existing = form.cleaned_data['clear_existing_scheduled']

            if clear_existing:
                season.games.filter(status='scheduled', game_type='regular').delete()

            rotation = list(teams)
            if len(rotation) % 2 == 1:
                rotation.append(None)

            n = len(rotation)
            num_rounds = n - 1
            half = n // 2
            created_count = 0

            rounds_matchups = []
            for r in range(num_rounds):
                week_pairs = []
                for i in range(half):
                    t1 = rotation[i]
                    t2 = rotation[n - 1 - i]
                    if t1 is not None and t2 is not None:
                        if r % 2 == 1 and i == 0:
                            week_pairs.append((t2, t1))
                        else:
                            week_pairs.append((t1, t2))
                rounds_matchups.append(week_pairs)
                rotation = [rotation[0]] + [rotation[-1]] + rotation[1:-1]

            if double_rr:
                second_half = [[(t2, t1) for (t1, t2) in week] for week in rounds_matchups]
                rounds_matchups.extend(second_half)

            for week_idx, week_pairs in enumerate(rounds_matchups, start=1):
                week_base_dt = start_dt + timedelta(days=7 * (week_idx - 1))
                for slot_idx, (home_team, away_team) in enumerate(week_pairs):
                    game_dt = week_base_dt + timedelta(hours=slot_idx)
                    Game.objects.create(
                        season=season,
                        team1=home_team,
                        team2=away_team,
                        date=game_dt,
                        location=location,
                        status='scheduled',
                        game_type='regular',
                        week_number=week_idx,
                    )
                    created_count += 1

            messages.success(
                request,
                f"Generated {created_count} round-robin games across {len(rounds_matchups)} weeks!"
            )
            return redirect('season_detail', season_id=season.id)
    else:
        default_dt = timezone.now().replace(hour=18, minute=30, second=0, microsecond=0) + timedelta(days=2)
        form = ScheduleGeneratorForm(initial={'start_datetime': default_dt.strftime('%Y-%m-%dT%H:%M')})

    return render(request, 'leagues/generate_schedule.html', {
        'form': form,
        'season': season,
        'team_count': len(teams),
    })


@login_required
def generate_playoffs(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    if not request.user.is_league_admin:
        messages.error(request, "Only league admins can generate playoff brackets.")
        return redirect('season_detail', season_id=season.id)

    standings = season.get_standings()
    if len(standings) < 2:
        messages.error(request, "Need at least 2 teams to generate playoffs.")
        return redirect('season_detail', season_id=season.id)

    if request.method == 'POST':
        season.games.filter(game_type__in=['playoff_qf', 'playoff_sf', 'playoff_final', 'consolation'], status='scheduled').delete()
        base_dt = timezone.now().replace(hour=19, minute=0, second=0, microsecond=0) + timedelta(days=7)

        if len(standings) >= 4:
            seed1 = standings[0]['team']
            seed2 = standings[1]['team']
            seed3 = standings[2]['team']
            seed4 = standings[3]['team']

            Game.objects.create(
                season=season,
                team1=seed1,
                team2=seed4,
                playoff_seed1=1,
                playoff_seed2=4,
                date=base_dt,
                location="Main Sanctuary Gym - Court 1",
                game_type='playoff_sf',
                week_number=99,
                notes="Semifinal #1: #1 Seed vs #4 Seed",
            )
            Game.objects.create(
                season=season,
                team1=seed2,
                team2=seed3,
                playoff_seed1=2,
                playoff_seed2=3,
                date=base_dt + timedelta(hours=1, minutes=15),
                location="Main Sanctuary Gym - Court 1",
                game_type='playoff_sf',
                week_number=99,
                notes="Semifinal #2: #2 Seed vs #3 Seed",
            )
            messages.success(request, "Top 4 Playoff Semifinal bracket generated from current standings!")
        else:
            seed1 = standings[0]['team']
            seed2 = standings[1]['team']
            Game.objects.create(
                season=season,
                team1=seed1,
                team2=seed2,
                playoff_seed1=1,
                playoff_seed2=2,
                date=base_dt,
                location="Main Sanctuary Gym - Championship Court",
                game_type='playoff_final',
                week_number=100,
                notes="Championship Final: #1 Seed vs #2 Seed",
            )
            messages.success(request, "Championship Final matchup generated (#1 vs #2)!")
        return redirect('playoff_bracket', season_id=season.id)

    return redirect('playoff_bracket', season_id=season.id)


@login_required
def advance_playoffs_to_final(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    if not request.user.is_league_admin:
        messages.error(request, "Only league admins can advance the playoff bracket.")
        return redirect('playoff_bracket', season_id=season.id)

    if request.method == 'POST':
        semis = list(season.games.filter(game_type='playoff_sf', status='completed').order_by('id'))
        if len(semis) < 2 or not semis[0].winner or not semis[1].winner:
            messages.error(request, "Both Semifinal games must be completed with a winner before generating the Championship Final.")
            return redirect('playoff_bracket', season_id=season.id)

        w1 = semis[0].winner
        w2 = semis[1].winner
        l1 = semis[0].team2 if semis[0].winner == semis[0].team1 else semis[0].team1
        l2 = semis[1].team2 if semis[1].winner == semis[1].team1 else semis[1].team1

        final_dt = semis[-1].date + timedelta(days=3)
        season.games.filter(game_type__in=['playoff_final', 'consolation'], status='scheduled').delete()

        Game.objects.create(
            season=season,
            team1=l1,
            team2=l2,
            date=final_dt,
            location="Main Sanctuary Gym - Fellowship Court",
            game_type='consolation',
            week_number=100,
            notes="3rd Place Fellowship Match",
        )
        Game.objects.create(
            season=season,
            team1=w1,
            team2=w2,
            date=final_dt + timedelta(hours=1, minutes=30),
            location="Main Sanctuary Gym - Championship Court",
            game_type='playoff_final',
            week_number=100,
            notes="League Championship Final",
        )
        messages.success(request, f"Championship Final ({w1.name} vs {w2.name}) and 3rd Place Match scheduled!")
    return redirect('playoff_bracket', season_id=season.id)


def playoff_bracket(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    standings = season.get_standings()
    semifinals = season.games.filter(game_type='playoff_sf').select_related('team1', 'team2')
    finals = season.games.filter(game_type='playoff_final').select_related('team1', 'team2')
    consolations = season.games.filter(game_type='consolation').select_related('team1', 'team2')
    champion = None
    for f in finals:
        if f.status == 'completed' and f.winner:
            champion = f.winner

    return render(request, 'leagues/playoff_bracket.html', {
        'season': season,
        'standings': standings,
        'semifinals': semifinals,
        'finals': finals,
        'consolations': consolations,
        'champion': champion,
    })


def game_detail(request, game_id):
    game = get_object_or_404(
        Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'current_batter'),
        id=game_id
    )
    player_stats = game.player_stats.select_related('player', 'team').all()
    sport = game.season.league.sport if game.season_id else 'basketball'
    suggested_categories = [name for name, _abbr in SPORT_DEFAULT_CATEGORIES.get(sport, SPORT_DEFAULT_CATEGORIES['other'])]

    score_form = None
    stat_form = None
    if request.user.can_record_scores:
        score_form = GameScoreForm(instance=game)
        stat_form = PlayerGameStatForm(game=game)

    return render(request, 'leagues/game_detail.html', {
        'game': game,
        'player_stats': player_stats,
        'score_form': score_form,
        'stat_form': stat_form,
        'suggested_categories': suggested_categories,
    })


@login_required
def record_game_score(request, game_id):
    game = get_object_or_404(Game.objects.select_related('season', 'team1', 'team2'), id=game_id)
    if not request.user.can_record_scores:
        messages.error(request, "You do not have permission to record game scores.")
        return redirect('game_detail', game_id=game.id)

    if request.method == 'POST':
        form = GameScoreForm(request.POST, instance=game)
        if form.is_valid():
            updated_game = form.save()
            messages.success(
                request,
                f"Updated score: {updated_game.team1.name} {updated_game.team1_score} - {updated_game.team2_score} {updated_game.team2.name} ({updated_game.get_status_display()})"
            )
    return redirect('game_detail', game_id=game.id)


@login_required
def add_game_stat(request, game_id):
    game = get_object_or_404(Game.objects.select_related('season', 'team1', 'team2'), id=game_id)
    if not request.user.can_record_scores:
        messages.error(request, "You do not have permission to record player stats.")
        return redirect('game_detail', game_id=game.id)

    if request.method == 'POST':
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


# ============================================================================
# SIMPLIFIED GAMECHANGER: 1-TAP LINEUP, LIVE DUGOUT CONSOLE & PUBLIC GAMECAST
# ============================================================================

def _serialize_batter(player):
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


def _serialize_game_state(game: Game):
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
            'position': e.field_position,
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
            'position': e.field_position,
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
        'current_inning': game.current_inning,
        'inning_half': game.inning_half,
        'inning_half_display': 'Top' if game.inning_half == 'top' else 'Bottom',
        'batting_team_name': batting_team.name,
        'outs': game.outs,
        'runner_on_first': game.runner_on_first,
        'runner_on_second': game.runner_on_second,
        'runner_on_third': game.runner_on_third,
        'current_batter': _serialize_batter(game.current_batter),
        'on_deck_batter': _serialize_batter(on_deck),
        'play_by_play': game.play_by_play or [],
        'team1_lineup': team1_lineup,
        'team2_lineup': team2_lineup,
        'is_diamond_sport': game.season.league.is_diamond_sport if game.season and game.season.league else False,
        'score_label': game.season.league.score_label if game.season and game.season.league else 'Points',
        'period_label': game.season.league.period_label if game.season and game.season.league else 'Period',
        'sport': game.season.league.sport if game.season and game.season.league else 'other',
        # Clock configurations
        'enable_game_clock': game.season.league.enable_game_clock if game.season and game.season.league else False,
        'default_period_minutes': game.season.league.default_period_minutes if game.season and game.season.league else 20,
        'enable_flag_football_clocks': game.season.league.enable_flag_football_clocks if game.season and game.season.league else False,
        'enable_time_limit_clock': game.season.league.enable_time_limit_clock if game.season and game.season.league else False,
        'enable_timeout_clock': game.season.league.enable_timeout_clock if game.season and game.season.league else True,
        'clock_seconds_remaining': game.clock_seconds_remaining,
        'clock_running': game.clock_running,
    }


def _increment_player_stat(player, game, team, category, delta=1):
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


@login_required
def dugout_console(request, game_id):
    """Single-Operator Live Dugout Console with 1-tap scoreboard, lineup check-in & auto walk-up music."""
    game = get_object_or_404(
        Game.objects.select_related('season__league', 'team1', 'team2', 'current_batter'),
        id=game_id
    )
    if not request.user.can_record_scores:
        messages.error(request, "Only coaches, scorekeepers, or admins can open the Dugout Operator Console.")
        return redirect('gamecast', game_id=game.id)

    game.ensure_lineups_initialized()
    if not game.current_batter:
        game.advance_to_next_batter()
        game.save(update_fields=['current_batter', 'team1_batter_index', 'team2_batter_index'])

    state = _serialize_game_state(game)
    return render(request, 'leagues/dugout_console.html', {
        'game': game,
        'initial_state_json': json.dumps(state),
    })


@login_required
def dugout_action(request, game_id):
    """AJAX endpoint for 1-tap Dugout Console actions so audio playback is never interrupted."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    game = get_object_or_404(
        Game.objects.select_related('season__league', 'team1', 'team2', 'current_batter'),
        id=game_id
    )
    if not request.user.can_record_scores:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    try:
        payload = json.loads(request.body.decode('utf-8')) if request.body else request.POST
    except json.JSONDecodeError:
        payload = request.POST

    action = payload.get('action', '')
    trigger_walkup = _apply_dugout_action_internal(game, action, payload)

    game.save()
    state = _serialize_game_state(game)
    state['trigger_walkup'] = trigger_walkup
    return JsonResponse(state)


def _apply_dugout_action_internal(game: Game, action: str, payload: dict):
    """Core action processor used by both single action and batch offline sync."""
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
        _increment_player_stat(batter, game, batting_team, 'Hits', 1)

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
            _increment_player_stat(batter, game, batting_team, 'Runs Batted In', runs_scored)
            game.log_play(f"{batter_name} singles! ({runs_scored} run scores)")
        else:
            game.log_play(f"{batter_name} hits a single (runner on 1B).")

        game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'walk':
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
        game.log_play(f"{batter_name} reaches first base (Walk).")
        game.advance_to_next_batter()
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

        _increment_player_stat(batter, game, batting_team, 'Hits', 1)
        _increment_player_stat(batter, game, batting_team, 'Home Runs', 1)
        _increment_player_stat(batter, game, batting_team, 'Runs Batted In', runs_scored)
        _increment_player_stat(batter, game, batting_team, 'Runs Scored', 1)

        game.log_play(f"HOME RUN by {batter_name}! ({runs_scored} R scored)")
        game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'out':
        game.outs += 1
        if game.outs >= 3:
            game.outs = 0
            game.runner_on_first = False
            game.runner_on_second = False
            game.runner_on_third = False
            if game.inning_half == 'top':
                game.inning_half = 'bottom'
                game.log_play(f"3rd out! Switching to Bottom of Inning {game.current_inning} ({game.team1.name} batting).")
            else:
                game.inning_half = 'top'
                game.current_inning += 1
                game.log_play(f"3rd out! Switching to Top of Inning {game.current_inning} ({game.team2.name} batting).")
            game.advance_to_next_batter()
            trigger_walkup = True
        else:
            game.log_play(f"{batter_name} recorded out ({game.outs} out).")
            game.advance_to_next_batter()
            trigger_walkup = True

    elif action == 'run_plus':
        team_target = payload.get('team', 'batting')
        points = int(payload.get('points', 1))
        label = game.season.league.score_label if (game.season and game.season.league) else 'Pts'
        if team_target == 'team1' or (team_target == 'batting' and batting_team == game.team1):
            game.team1_score += points
            game.log_play(f"+{points} {label} for {game.team1.name} ({game.team1_score}-{game.team2_score}).")
        else:
            game.team2_score += points
            game.log_play(f"+{points} {label} for {game.team2.name} ({game.team1_score}-{game.team2_score}).")

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

    elif action == 'mark_final':
        game.status = 'completed'
        game.log_play(f"FINAL SCORE: {game.team1.name} {game.team1_score}, {game.team2.name} {game.team2_score}")

        # Dispatch Discord Webhook for Game Final
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


@login_required
def dugout_batch_sync(request, game_id):
    """Flush and sync offline queued actions in chronological order."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    game = get_object_or_404(
        Game.objects.select_related('season__league', 'team1', 'team2', 'current_batter'),
        id=game_id
    )
    if not request.user.can_record_scores:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
        actions = data.get('actions', [])
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

    applied_count = 0
    for item in actions:
        act = item.get('action')
        if act:
            _apply_dugout_action_internal(game, act, item)
            applied_count += 1

    game.save()
    state = _serialize_game_state(game)
    state['synced_count'] = applied_count
    return JsonResponse(state)


def game_live_state(request, game_id):
    """Public JSON endpoint polled by the Live GameCast view."""
    game = get_object_or_404(
        Game.objects.select_related('season__league', 'team1', 'team2', 'current_batter'),
        id=game_id
    )
    return JsonResponse(_serialize_game_state(game))


def gamecast(request, game_id):
    """Public mobile-friendly Live GameCast scoreboard & diamond view for parents and spectators."""
    game = get_object_or_404(
        Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'current_batter'),
        id=game_id
    )
    game.ensure_lineups_initialized()
    state = _serialize_game_state(game)
    return render(request, 'leagues/gamecast.html', {
        'game': game,
        'initial_state_json': json.dumps(state),
    })


@login_required
def practice_sandbox(request):
    """
    Practice & Training Sandbox:
    Interactive practice game allowing volunteers, coaches, and umpires to test
    all controls, clocks, walk-up songs, and scoring with zero consequences to official stats.
    """
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
