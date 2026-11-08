import datetime
from datetime import timedelta
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.utils import timezone
from django.db.models import F, Max, Q
from .models import (League, Season, Team, SeasonRegistration, Game, GameLineupEntry, GameRSVP, GameOfficialAssignment, LeagueVenue, PlayerDisciplinaryRecord, GameSportsmanshipRating)
from core.services.notifications import send_discord_notification, send_twilio_sms
from .forms import (
    LeagueForm, SeasonForm, TeamForm, SeasonRegistrationForm,
    GameForm, GameScoreForm, ScheduleGeneratorForm
)
from stats.models import PlayerGameStat, SPORT_DEFAULT_CATEGORIES
from stats.forms import PlayerGameStatForm
from leagues.services.scheduler import ScheduleGeneratorService
from leagues.services.calendar_feed import generate_ics_feed
from users.models import CustomUser


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
            # Inherit officials from league master pool
            if league.master_officials_pool.exists():
                season.officials_pool.add(*league.master_officials_pool.all())
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
    can_manage_league = False
    today = timezone.localdate()
    today_games_count = season.games.filter(date__date=today, status='scheduled').count()

    if request.user.is_authenticated:
        user_registration = registrations.filter(player=request.user).first()
        can_manage_league = request.user.can_manage_league(season.league)

    return render(request, 'leagues/season_detail.html', {
        'season': season,
        'league': season.league,
        'standings': standings,
        'regular_games': regular_games,
        'playoff_games': playoff_games,
        'registrations': registrations,
        'user_registration': user_registration,
        'can_manage_league': can_manage_league,
        'today': today,
        'today_games_count': today_games_count,
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
    from core.models import Church
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    user = request.user

    # Option A: Church Commissioners register teams for their church and designate Team Captains
    if not (user.is_league_admin or user.is_church_commissioner or user.role in ('coach', 'church_admin')):
        messages.error(request, "Only Church Commissioners or League Administrators can register teams in a season.")
        return redirect('season_detail', season_id=season.id)

    target_church = None
    church_id = request.GET.get('church_id')
    if church_id:
        target_church = Church.objects.filter(id=church_id).first()
    if not target_church:
        target_church = user.managed_churches.first() or user.church

    if request.method == 'POST':
        form = TeamForm(request.POST, user=user, target_church=target_church)
        if form.is_valid():
            team = form.save(commit=False)
            team.season = season
            team.league = season.league
            team.save()

            if team.captain:
                team.players.add(team.captain)
                SeasonRegistration.objects.update_or_create(
                    season=season,
                    player=team.captain,
                    defaults={
                        'preferred_team': team,
                        'status': 'approved',
                        'waiver_agreed': team.captain.waiver_signed,
                    }
                )
            messages.success(request, f"Team '{team.name}' registered successfully! The Team Captain can now invite players.")
            return redirect('team_detail', team_id=team.id)
    else:
        form = TeamForm(user=user, target_church=target_church, initial={
            'church': target_church,
            'captain': user if user.role == 'coach' else None,
        })
    return render(request, 'leagues/create_team.html', {
        'form': form,
        'season': season,
        'target_church': target_church,
    })


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
        request.user.is_authenticated and request.user.can_manage_team(team)
    )
    invite_url = team.get_invite_url(request)

    available_church_members = []
    if is_captain_or_admin and team.church:
        available_church_members = list(
            team.church.members.exclude(id__in=team.players.values_list('id', flat=True)).order_by('first_name', 'last_name')
        )

    return render(request, 'leagues/team_detail.html', {
        'team': team,
        'games': games,
        'pending_requests': pending_requests,
        'is_captain_or_admin': is_captain_or_admin,
        'invite_url': invite_url,
        'available_church_members': available_church_members,
    })


@login_required
def manage_roster_player(request, team_id):
    team = get_object_or_404(Team.objects.select_related('league', 'season', 'church'), id=team_id)
    if not request.user.can_manage_team(team):
        messages.error(request, f"You do not have permission to manage the roster for {team.name}.")
        return redirect('team_detail', team_id=team.id)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_player':
            player_id = request.POST.get('player_id')
            player = get_object_or_404(CustomUser, id=player_id)
            if not team.players.filter(id=player.id).exists():
                messages.error(request, f"{player.display_name} is not on this team's roster.")
                return redirect('team_detail', team_id=team.id)

            jersey_val = request.POST.get('jersey_number', '').strip()
            pos_val = request.POST.get('preferred_position', '').strip()
            gender_val = request.POST.get('gender', '').strip()

            if jersey_val and jersey_val.isdigit():
                player.jersey_number = int(jersey_val)
            elif jersey_val == '':
                player.jersey_number = None

            if pos_val:
                player.preferred_position = pos_val

            if gender_val in ('M', 'F', 'O', ''):
                player.gender = gender_val

            player.save(update_fields=['jersey_number', 'preferred_position', 'gender'])

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'status': 'ok',
                    'player_id': player.id,
                    'jersey_number': player.jersey_number,
                    'preferred_position': player.preferred_position,
                    'gender': player.gender,
                })
            messages.success(request, f"Updated roster profile for {player.display_name}.")

        elif action == 'remove_player':
            player_id = request.POST.get('player_id')
            player = get_object_or_404(CustomUser, id=player_id)
            if player.id == team.captain_id:
                messages.error(request, "Cannot drop the team captain. Assign a different captain first.")
            else:
                team.players.remove(player)
                GameLineupEntry.objects.filter(team=team, player=player, game__status='scheduled').delete()
                messages.success(request, f"Removed {player.display_name} from the {team.name} roster.")

        elif action == 'set_captain':
            player_id = request.POST.get('player_id')
            player = get_object_or_404(CustomUser, id=player_id)
            if team.players.filter(id=player.id).exists():
                team.captain = player
                team.save(update_fields=['captain'])
                messages.success(request, f"Assigned {player.display_name} as Team Captain for {team.name}!")
            else:
                messages.error(request, "New captain must be on the team roster.")

        elif action == 'quick_add_player':
            if team.players.count() >= team.season.max_roster_size:
                messages.error(request, f"Cannot add player: '{team.name}' has reached the roster cap ({team.season.max_roster_size}).")
            else:
                player_id = request.POST.get('player_id')
                player = get_object_or_404(CustomUser, id=player_id)
                if (team.church and player.church_id == team.church_id) or player.is_free_agent or request.user.can_manage_league(team.league):
                    team.players.add(player)
                    SeasonRegistration.objects.update_or_create(
                        season=team.season,
                        player=player,
                        defaults={
                            'preferred_team': team,
                            'status': 'approved',
                            'waiver_agreed': player.waiver_signed,
                        }
                    )
                    messages.success(request, f"⚡ Added {player.display_name} to {team.name} roster!")
                else:
                    messages.error(request, f"{player.display_name} is not a member of {team.church.name if team.church else 'this church'}.")

    return redirect('team_detail', team_id=team.id)


@login_required
def join_team(request, team_id):
    team = get_object_or_404(Team.objects.select_related('season'), id=team_id)
    messages.info(request, "Joining a team roster requires an invite link from the Team Captain or an assignment by your Church Commissioner.")
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
    reg = get_object_or_404(SeasonRegistration.objects.select_related('season__league', 'player__church', 'preferred_team__church'), id=reg_id)
    user = request.user
    if not user.can_manage_teams:
        messages.error(request, "You do not have permission to manage registrations.")
        return redirect('season_detail', season_id=reg.season_id)

    if request.method == 'POST':
        team_id = request.POST.get('team_id')
        action = request.POST.get('action', 'approve')
        if action == 'toggle_dues':
            can_manage_dues = (
                user.is_overall_commissioner or
                user.can_manage_league(reg.season.league) or
                (reg.player.church and user.can_manage_church(reg.player.church))
            )
            if not can_manage_dues:
                messages.error(request, "Only Church or League Commissioners can update player dues status.")
                return redirect('season_detail', season_id=reg.season_id)

            reg.dues_paid = not reg.dues_paid
            reg.save(update_fields=['dues_paid'])
            messages.success(request, f"Updated dues status for {reg.player.display_name}.")
        elif action == 'approve':
            target_team = get_object_or_404(Team, id=team_id, season=reg.season) if team_id else reg.preferred_team
            if not target_team:
                messages.error(request, "Please select a team to assign this player to.")
                return redirect('season_detail', season_id=reg.season_id)

            can_assign_to_target = (
                user.is_overall_commissioner or
                user.can_manage_league(reg.season.league) or
                user.can_manage_church(target_team.church) or
                target_team.captain_id == user.id
            )
            if not can_assign_to_target:
                messages.error(request, f"You do not have permission to roster players to {target_team.name}.")
                return redirect('season_detail', season_id=reg.season_id)

            target_team.players.add(reg.player)
            reg.preferred_team = target_team
            reg.status = 'approved'
            reg.is_free_agent = False
            reg.save()
            reg.player.is_free_agent = False
            reg.player.save(update_fields=['is_free_agent'])
            messages.success(request, f"{reg.player.display_name} assigned to {target_team.name}!")
    return redirect('season_detail', season_id=reg.season_id)


@login_required
def create_game(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    if not request.user.can_manage_league(season.league):
        messages.error(request, "Only League Commissioners or Overall Admins can schedule league games.")
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
    if not request.user.can_manage_league(season.league):
        messages.error(request, "Only the League Commissioner for this league can auto-generate schedules.")
        return redirect('season_detail', season_id=season.id)

    teams = list(season.teams.all())
    if len(teams) < 2:
        messages.error(request, "At least 2 teams are required in the season to generate a schedule.")
        return redirect('season_detail', season_id=season.id)

    preview_games = None

    if request.method == 'POST':
        form = ScheduleGeneratorForm(request.POST)
        if form.is_valid():
            start_date = form.cleaned_data['start_date']
            game_days = form.cleaned_data['parsed_game_days']
            time_slots = form.cleaned_data['parsed_time_slots']
            venues = form.cleaned_data['parsed_venues']
            blackout_dates = form.cleaned_data['parsed_blackout_dates']
            protect_wednesdays = form.cleaned_data.get('protect_wednesdays', True)
            protect_sunday_mornings = form.cleaned_data.get('protect_sunday_mornings', True)
            double_rr = form.cleaned_data.get('double_round_robin', False)
            add_buffer = form.cleaned_data.get('add_weather_buffer', True)
            clear_existing = form.cleaned_data.get('clear_existing_scheduled', True)

            service = ScheduleGeneratorService(
                season=season,
                start_date=start_date,
                game_days=game_days,
                time_slots=time_slots,
                venues=venues,
                blackout_dates=blackout_dates,
                protect_wednesdays=protect_wednesdays,
                protect_sunday_mornings=protect_sunday_mornings,
                double_round_robin=double_rr,
                add_weather_buffer=add_buffer,
            )

            action = request.POST.get('action', 'generate')
            if action == 'preview':
                preview_games = service.plan_schedule()
                messages.info(request, f"Generated draft schedule preview with {len(preview_games)} matchups. Review below and click 'Save & Publish Schedule' to confirm.")
            else:
                created_count = service.execute_and_save(clear_existing_scheduled=clear_existing)
                messages.success(
                    request,
                    f"Successfully generated and published {created_count} regular-season games!"
                )
                return redirect('season_detail', season_id=season.id)
    else:
        tomorrow = timezone.localdate() + datetime.timedelta(days=1)
        form = ScheduleGeneratorForm(initial={
            'start_date': tomorrow,
            'game_days': ['1', '3'],
            'time_slots': '18:30, 19:45',
            'venues': "Court 1\nCourt 2",
            'protect_wednesdays': True,
            'protect_sunday_mornings': True,
            'double_round_robin': False,
            'add_weather_buffer': True,
            'clear_existing_scheduled': True,
        })

    return render(request, 'leagues/generate_schedule.html', {
        'form': form,
        'season': season,
        'team_count': len(teams),
        'preview_games': preview_games,
    })


@login_required
def generate_playoffs(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    if not request.user.can_manage_league(season.league):
        messages.error(request, "Only the League Commissioner for this league can generate playoff brackets.")
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
    if not request.user.can_manage_league(season.league):
        messages.error(request, "Only the League Commissioner for this league can advance the playoff bracket.")
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

    can_score = request.user.is_authenticated and request.user.can_score_game(game)
    score_form = None
    stat_form = None
    if can_score:
        score_form = GameScoreForm(instance=game)
        stat_form = PlayerGameStatForm(game=game)

    user = request.user
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

    # Score confirmation & dispute authority flags
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
        if is_commish:
            can_confirm_score = True
            can_dispute_score = True
        elif user != game.score_submitted_by:
            can_confirm_score = True
            can_dispute_score = True

    return render(request, 'leagues/game_detail.html', {
        'game': game,
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


@login_required
def record_game_score(request, game_id):
    game = get_object_or_404(Game.objects.select_related('season__league', 'team1__church', 'team2__church'), id=game_id)
    if not request.user.can_score_game(game):
        messages.error(request, "You do not have permission to record game scores for this match.")
        return redirect('game_detail', game_id=game.id)

    # Authority check: If game has an assigned official and official already finalized score, coaches cannot overwrite
    assigned_official_ids = game.get_assigned_official_user_ids()
    is_assigned_official = request.user.id in assigned_official_ids
    is_commish = request.user.is_overall_commissioner or (game.season and game.season.league and request.user.can_manage_league(game.season.league))

    if game.score_confirmed and game.score_submitted_by_id in assigned_official_ids and not (is_assigned_official or is_commish):
        messages.error(request, "This game was finalized by the official referee. To request a correction, please contact your league commissioner.")
        return redirect('game_detail', game_id=game.id)

    if request.method == 'POST':
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


@login_required
def add_game_stat(request, game_id):
    game = get_object_or_404(Game.objects.select_related('season__league', 'team1__church', 'team2__church'), id=game_id)
    if not request.user.can_score_game(game):
        messages.error(request, "You do not have permission to record player stats for this match.")
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
        Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'current_batter', 'active_scorer'),
        id=game_id
    )
    if not request.user.can_score_game(game):
        messages.error(request, "Only assigned referees, participating team captains, or league commissioners can open the Dugout Operator Console for this match.")
        return redirect('gamecast', game_id=game.id)

    game.ensure_lineups_initialized()
    if not game.current_batter:
        game.advance_to_next_batter()
        game.save(update_fields=['current_batter', 'team1_batter_index', 'team2_batter_index'])

    is_locked = game.is_scorer_locked(request.user)
    if not is_locked:
        # Acquire or renew lock
        game.acquire_scorer_lock(request.user)
        game.save(update_fields=['active_scorer', 'active_scorer_expires_at'])

    state = _serialize_game_state(game)
    state['is_locked'] = is_locked
    return render(request, 'leagues/dugout_console.html', {
        'game': game,
        'initial_state_json': json.dumps(state),
        'is_locked': is_locked,
        'active_scorer': game.active_scorer,
    })


@login_required
def dugout_action(request, game_id):
    """AJAX endpoint for 1-tap Dugout Console actions so audio playback is never interrupted."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    game = get_object_or_404(
        Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'current_batter', 'active_scorer'),
        id=game_id
    )
    if not request.user.can_score_game(game):
        return JsonResponse({'error': 'Permission denied: you cannot score this match'}, status=403)

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

    # Allow takeover action regardless of current lock
    if action == 'take_over_scoring':
        game.acquire_scorer_lock(request.user)
        game.log_score_event(request.user, 'scorer_takeover', f"Scorekeeping taken over by {request.user.display_name}")
        game.save(update_fields=['active_scorer', 'active_scorer_expires_at', 'score_audit_log'])
        state = _serialize_game_state(game)
        state['is_locked'] = False
        return JsonResponse(state)

    # Check lock for regular actions
    if game.is_scorer_locked(request.user):
        scorer_name = game.active_scorer.display_name if game.active_scorer else "another scorekeeper"
        return JsonResponse({
            'error': f"Game scoring is currently active by {scorer_name}. You are in view-only mode.",
            'locked': True,
            'active_scorer': scorer_name,
            'active_scorer_id': game.active_scorer_id,
        }, status=423)

    # Refresh lock on valid action
    game.acquire_scorer_lock(request.user)

    if action == 'undo':
        success = game.pop_snapshot()
        if success:
            game.log_score_event(request.user, 'undo_play', f"Undone last action by {request.user.display_name}")
            game.save()
        state = _serialize_game_state(game)
        state['trigger_walkup'] = False
        state['is_locked'] = False
        state['undone'] = success
        return JsonResponse(state)

    # Save state snapshot BEFORE mutating action
    game.push_snapshot()

    if action == 'mark_final':
        game.submit_score(request.user)
        game.log_play(f"FINAL SCORE: {game.team1.name} {game.team1_score}, {game.team2.name} {game.team2_score}")
        trigger_walkup = False
    else:
        trigger_walkup = _apply_dugout_action_internal(game, action, payload)

    game.save()
    state = _serialize_game_state(game)
    state['trigger_walkup'] = trigger_walkup
    state['is_locked'] = False
    return JsonResponse(state)


def _check_inning_run_limit(game, runs_added):
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
        _handle_side_retired(game, reason=f"Inning run limit of {league.inning_run_limit} runs reached")
        return True
    return False


def _handle_side_retired(game, reason="3 outs recorded"):
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


def _apply_walk_outcome(game, batter, batting_team, batter_name):
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
        _increment_player_stat(batter, game, batting_team, 'Runs Batted In', 1)
        game.log_play(f"{batter_name} walks with bases loaded! (+1 run scores).")
    else:
        game.log_play(f"{batter_name} reaches first base (Walk / BB).")

    side_retired = _check_inning_run_limit(game, runs_scored)
    if not side_retired:
        game.advance_to_next_batter()


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

        side_retired = _check_inning_run_limit(game, runs_scored)
        if not side_retired:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'double':
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
            _increment_player_stat(batter, game, batting_team, 'Runs Batted In', runs_scored)
            game.log_play(f"{batter_name} doubles! ({runs_scored} run(s) scored)")
        else:
            game.log_play(f"{batter_name} hits a double (runner on 2B).")

        side_retired = _check_inning_run_limit(game, runs_scored)
        if not side_retired:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'triple':
        if batting_team == game.team1:
            game.team1_hits += 1
        else:
            game.team2_hits += 1
        _increment_player_stat(batter, game, batting_team, 'Hits', 1)

        runs_scored = int(game.runner_on_first) + int(game.runner_on_second) + int(game.runner_on_third)
        game.runner_on_first = False
        game.runner_on_second = False
        game.runner_on_third = True

        if runs_scored:
            if batting_team == game.team1:
                game.team1_score += runs_scored
            else:
                game.team2_score += runs_scored
            _increment_player_stat(batter, game, batting_team, 'Runs Batted In', runs_scored)
            game.log_play(f"{batter_name} triples! ({runs_scored} run(s) scored)")
        else:
            game.log_play(f"{batter_name} hits a triple (runner on 3B).")

        side_retired = _check_inning_run_limit(game, runs_scored)
        if not side_retired:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'walk':
        _apply_walk_outcome(game, batter, batting_team, batter_name)
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
        side_retired = _check_inning_run_limit(game, runs_scored)
        if not side_retired:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'out':
        game.outs += 1
        if game.outs >= 3:
            _handle_side_retired(game, reason="3 outs recorded")
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
            _increment_player_stat(batter, game, batting_team, 'Runs Batted In', 1)

        act_label = "Sacrifice Fly" if action == 'sacrifice_fly' else "RBI Groundout"
        if runs_scored:
            game.log_play(f"{batter_name} hits {act_label}. Run scores! ({game.outs} out)")
        else:
            game.log_play(f"{batter_name} recorded out ({game.outs} out).")

        side_retired = _check_inning_run_limit(game, runs_scored)
        if not side_retired:
            if game.outs >= 3:
                _handle_side_retired(game, reason="3 outs recorded")
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
            _handle_side_retired(game, reason="3 outs recorded")
        else:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'strikeout':
        game.outs += 1
        style = payload.get('style', 'swinging')
        style_label = "swinging (K)" if style == 'swinging' else "looking (ꓘ)"
        game.log_play(f"{batter_name} strikes out {style_label} ({game.outs} out).")
        if game.outs >= 3:
            _handle_side_retired(game, reason="3 outs recorded")
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

        side_retired = _check_inning_run_limit(game, runs_scored)
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
            _check_inning_run_limit(game, 1)
        elif to_base == 'out':
            game.outs += 1
            game.log_play(f"Runner put out on basepath from {from_base} ({game.outs} out).")
            if game.outs >= 3:
                _handle_side_retired(game, reason="3 outs recorded")
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
            _handle_side_retired(game, reason=f"{label} recorded")
        else:
            game.advance_to_next_batter()
        trigger_walkup = True

    elif action == 'count_ball':
        game.balls += 1
        if game.balls >= 4:
            _apply_walk_outcome(game, batter, batting_team, batter_name)
            trigger_walkup = True
        else:
            game.log_play(f"Ball {game.balls} to {batter_name} (Count: {game.balls}-{game.strikes}).")

    elif action == 'count_strike':
        game.strikes += 1
        if game.strikes >= 3:
            game.outs += 1
            game.log_play(f"{batter_name} strikes out on Strike 3 ({game.outs} out).")
            if game.outs >= 3:
                _handle_side_retired(game, reason="3 outs recorded")
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
                    _handle_side_retired(game, reason="3 outs recorded")
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
                _check_inning_run_limit(game, points)
        else:
            game.team2_score += points
            game.log_play(f"+{points} {label} for {game.team2.name} ({game.team1_score}-{game.team2_score}).")
            if game.season and game.season.league and game.season.league.is_diamond_sport:
                _check_inning_run_limit(game, points)

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
            _increment_player_stat(player, game, batting_team, 'Fouls', 1)
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


@login_required
def dugout_batch_sync(request, game_id):
    """Flush and sync offline queued actions in chronological order."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    game = get_object_or_404(
        Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'current_batter'),
        id=game_id
    )
    if not request.user.can_score_game(game):
        return JsonResponse({'error': 'Permission denied: you cannot score this match'}, status=403)

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


@login_required
def game_rsvp(request, game_id):
    """1-Tap Attendance RSVP endpoint for players on team rosters."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

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

    # Sync with GameLineupEntry if initialized
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


@login_required
def game_lineup_builder(request, game_id, team_id):
    """
    Upcoming Game Lineup & Multi-Position Defensive Rotation Builder.
    Allows coaches to configure batting orders and positions/rotations across innings/periods
    ahead of game day, automatically factoring in confirmed player RSVPs.
    """
    game = get_object_or_404(
        Game.objects.select_related('season__league', 'team1__church', 'team2__church'),
        id=game_id
    )
    team = get_object_or_404(
        Team.objects.select_related('church', 'captain', 'season__league'),
        id=team_id
    )

    if team not in (game.team1, game.team2):
        messages.error(request, f"{team.name} is not participating in this game.")
        return redirect('game_detail', game_id=game.id)

    user = request.user
    can_manage_lineup = user.can_manage_team(team)
    if not can_manage_lineup:
        messages.error(request, f"You do not have permission to manage the lineup for {team.name}.")
        return redirect('game_detail', game_id=game.id)

    game.ensure_lineups_initialized()

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

    if request.method == 'POST':
        action = request.POST.get('action', 'save_lineup')

        if action == 'autofill_rsvps':
            # Move confirmed players ('yes') to top of lineup, benches 'no'
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
            return redirect('game_lineup_builder', game_id=game.id, team_id=team.id)

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
            return redirect('game_lineup_builder', game_id=game.id, team_id=team.id)

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
            return redirect('game_lineup_builder', game_id=game.id, team_id=team.id)

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
            return redirect('game_lineup_builder', game_id=game.id, team_id=team.id)

        elif action == 'add_emergency_sub':
            league_obj = game.season.league if (game.season and game.season.league) else None
            if not (league_obj and league_obj.allow_emergency_subs):
                messages.error(request, "Emergency substitutes are not permitted in this league.")
                return redirect('game_lineup_builder', game_id=game.id, team_id=team.id)
            if game.game_type != 'regular':
                messages.error(request, "Emergency substitutes are strictly prohibited in playoff tournament games.")
                return redirect('game_lineup_builder', game_id=game.id, team_id=team.id)

            sub_user_id = request.POST.get('sub_user_id')
            consent_confirmed = bool(request.POST.get('consent_confirmed'))
            if not consent_confirmed:
                messages.warning(request, "You must certify that the opposing team's coach agreed to this emergency pickup player.")
                return redirect('game_lineup_builder', game_id=game.id, team_id=team.id)

            from users.models import CustomUser
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
            return redirect('game_lineup_builder', game_id=game.id, team_id=team.id)

        elif action == 'save_lineup':
            entries = list(game.lineup_entries.filter(team=team).select_related('player'))
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
                # Hard lock: Ineligible or suspended players cannot be marked present
                league_obj = game.season.league if (game.season and game.season.league) else None
                eligible, _ = entry.player.is_eligible_to_play(league_obj)
                entry.is_present = (present_val and eligible)
                entry.save(update_fields=['batting_order', 'field_position', 'position_rotations', 'is_present'])

            messages.success(request, f"Saved batting order and defensive rotations for {team.name}!")
            return redirect('game_lineup_builder', game_id=game.id, team_id=team.id)

    entries = list(
        game.lineup_entries.filter(team=team)
        .select_related('player')
        .order_by('batting_order', 'id')
    )
    rsvps = {r.player_id: r for r in game.rsvps.filter(player__in=team.players.all())}
    is_playoff = (game.game_type == 'playoff')
    league_obj = game.season.league if (game.season and game.season.league) else None
    for e in entries:
        e.rsvp = rsvps.get(e.player_id)
        e.rotation_dict = e.position_rotations or {}
        # Evaluate participant eligibility (suspensions, expulsions, minor waivers)
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

    # Co-ed analysis
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

    # Fair play / Playing time per player across periods
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

    return render(request, 'leagues/lineup_builder.html', {
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
    })


def game_lineup_print(request, game_id, team_id):
    """Clean, print-optimized umpire and dugout lineup card (RFC/standard format)."""
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


# ==============================================================================
# Smart Scheduling, Weather Rainout, Calendar Feeds (.ics), and Master Grid
# ==============================================================================

def team_calendar_ics(request, team_id):
    team = get_object_or_404(Team.objects.select_related('season', 'season__league'), id=team_id)
    games = Game.objects.filter(
        Q(team1=team) | Q(team2=team)
    ).select_related('team1', 'team2', 'season', 'season__league').order_by('date')

    cal_name = f"{team.name} ({team.season.name if team.season else 'SportsBall'})"
    ics_body = generate_ics_feed(games, calendar_name=cal_name, request=request)
    filename = f"{team.name.replace(' ', '_')}_schedule.ics"

    response = HttpResponse(ics_body, content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def season_calendar_ics(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    games = season.games.select_related('team1', 'team2', 'season', 'season__league').order_by('date')

    cal_name = f"{season.league.name} - {season.name} Master Schedule"
    ics_body = generate_ics_feed(games, calendar_name=cal_name, request=request)
    filename = f"{season.name.replace(' ', '_')}_master_schedule.ics"

    response = HttpResponse(ics_body, content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def user_calendar_ics(request):
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


@login_required
def rainout_today_games(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    if not request.user.can_manage_league(season.league):
        messages.error(request, "Only League Commissioners can postpone or rain out games.")
        return redirect('season_detail', season_id=season.id)

    target_date_str = request.GET.get('date') or request.POST.get('date')
    if target_date_str:
        try:
            target_date = datetime.datetime.strptime(target_date_str, '%Y-%m-%d').date()
        except ValueError:
            target_date = timezone.localdate()
    else:
        target_date = timezone.localdate()

    games_today = list(season.games.filter(date__date=target_date, status='scheduled'))
    if not games_today:
        messages.warning(request, f"No scheduled games found on {target_date.strftime('%B %d, %Y')} to postpone.")
        return redirect('season_detail', season_id=season.id)

    action = request.POST.get('action') or request.GET.get('action') or 'reschedule_makeup'

    max_week = season.games.filter(game_type='regular').aggregate(Max('week_number'))['week_number__max'] or 1
    makeup_week = max_week + 1

    count = len(games_today)
    for g in games_today:
        orig_date_str = g.date.strftime('%a %b %d')
        if action == 'postpone_only':
            g.status = 'postponed'
            g.notes = f"Postponed / Weather rainout on {orig_date_str}. {g.notes or ''}".strip()
            g.save(update_fields=['status', 'notes'])
        else:
            weeks_ahead = max(1, makeup_week - (g.week_number or 1))
            g.date = g.date + datetime.timedelta(days=7 * weeks_ahead)
            g.week_number = makeup_week
            g.status = 'scheduled'
            g.notes = f"Rescheduled from rainout on {orig_date_str}. {g.notes or ''}".strip()
            g.save(update_fields=['date', 'week_number', 'status', 'notes'])

    if action == 'postpone_only':
        messages.warning(request, f"🌧️ Weather Rainout: {count} game(s) on {target_date.strftime('%b %d')} have been marked Postponed.")
    else:
        messages.success(request, f"🌧️ Weather Rainout: {count} game(s) from {target_date.strftime('%b %d')} have been moved to Makeup Week {makeup_week}!")

    return redirect('schedule_grid', season_id=season.id)


def schedule_grid(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    can_manage = request.user.is_authenticated and request.user.can_manage_league(season.league)

    games = season.games.select_related('team1', 'team2').order_by('week_number', 'date', 'location')

    weeks_dict = {}
    for g in games:
        w = g.week_number or 1
        if w not in weeks_dict:
            weeks_dict[w] = []
        weeks_dict[w].append(g)

    weeks = sorted(weeks_dict.items(), key=lambda x: x[0])
    today = timezone.localdate()
    today_games_count = season.games.filter(date__date=today, status='scheduled').count()

    return render(request, 'leagues/schedule_grid.html', {
        'season': season,
        'weeks': weeks,
        'can_manage': can_manage,
        'today': today,
        'today_games_count': today_games_count,
    })


@login_required
def swap_game_slots(request, season_id):
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    if not request.user.can_manage_league(season.league):
        messages.error(request, "Only League Commissioners can swap game slots.")
        return redirect('schedule_grid', season_id=season.id)

    if request.method == 'POST':
        game1_id = request.POST.get('game1_id')
        game2_id = request.POST.get('game2_id')

        g1 = get_object_or_404(Game, id=game1_id, season=season)
        g2 = get_object_or_404(Game, id=game2_id, season=season)

        g1.date, g2.date = g2.date, g1.date
        g1.location, g2.location = g2.location, g1.location
        g1.week_number, g2.week_number = g2.week_number, g1.week_number

        g1.save(update_fields=['date', 'location', 'week_number'])
        g2.save(update_fields=['date', 'location', 'week_number'])

        messages.success(request, f"Successfully swapped slots between '{g1.team1.name} vs {g1.team2.name}' and '{g2.team1.name} vs {g2.team2.name}'.")

    return redirect('schedule_grid', season_id=season.id)


# ==============================================================================
# Officials & Umpires Scheduling, Sub Pool, and Budget Management
# ==============================================================================

@login_required
def officials_hub(request, season_id):
    """Command Center for managing the officials pool, game assignments, and pay budget."""
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    if not request.user.can_manage_league(season.league):
        messages.error(request, "Only League Commissioners can manage officials and budget.")
        return redirect('season_detail', season_id=season.id)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_budget':
            budget_val = request.POST.get('officials_budget', '0').strip()
            pay_val = request.POST.get('official_default_pay', '30').strip()
            try:
                season.officials_budget = float(budget_val)
                season.official_default_pay = float(pay_val)
                season.save(update_fields=['officials_budget', 'official_default_pay'])
                messages.success(request, "Updated officials season budget and default pay rate.")
            except ValueError:
                messages.error(request, "Invalid budget or pay amount.")

        elif action in ('add_to_pool', 'add_pool_member'):
            user_id = request.POST.get('user_id')
            user_to_add = get_object_or_404(CustomUser, id=user_id)
            season.officials_pool.add(user_to_add)
            messages.success(request, f"Added {user_to_add.display_name} to the season officials pool.")

        elif action in ('remove_from_pool', 'remove_pool_member'):
            user_id = request.POST.get('user_id')
            user_to_remove = get_object_or_404(CustomUser, id=user_id)
            season.officials_pool.remove(user_to_remove)
            messages.success(request, f"Removed {user_to_remove.display_name} from the officials pool.")

        elif action == 'assign_official':
            game_id = request.POST.get('game_id')
            official_id = request.POST.get('official_id')
            role = request.POST.get('role', 'head_ref')
            pay_val = request.POST.get('pay_amount') or season.official_default_pay

            game = get_object_or_404(Game, id=game_id, season=season)
            official = get_object_or_404(CustomUser, id=official_id)

            GameOfficialAssignment.objects.update_or_create(
                game=game,
                role=role,
                defaults={
                    'official': official,
                    'status': 'assigned',
                    'pay_amount': pay_val,
                    'pay_status': 'unpaid',
                }
            )
            # Ensure official is in the season pool
            season.officials_pool.add(official)
            messages.success(request, f"Assigned {official.display_name} as {role} for {game}.")

        elif action == 'remove_assignment':
            assignment_id = request.POST.get('assignment_id')
            GameOfficialAssignment.objects.filter(id=assignment_id, game__season=season).delete()
            messages.success(request, "Removed official assignment.")

        elif action == 'toggle_pay_status':
            assignment_id = request.POST.get('assignment_id')
            assignment = get_object_or_404(GameOfficialAssignment, id=assignment_id, game__season=season)
            assignment.toggle_payment()
            messages.success(request, f"Marked {assignment.official.display_name} as {assignment.get_pay_status_display()}.")

        return redirect('officials_hub', season_id=season.id)

    budget_summary = season.get_officials_budget_summary()
    pool_members = season.officials_pool.all().order_by('first_name', 'last_name')
    pool_ids = set(pool_members.values_list('id', flat=True))

    candidate_officials = CustomUser.objects.filter(
        Q(role__in=['referee', 'coach', 'admin']) | Q(is_staff=True)
    ).exclude(id__in=pool_ids).order_by('first_name', 'last_name')[:25]

    games = season.games.select_related('team1', 'team2').prefetch_related('official_assignments__official').order_by('week_number', 'date', 'location')

    weeks_dict = {}
    for g in games:
        w = g.week_number or 1
        if w not in weeks_dict:
            weeks_dict[w] = []
        weeks_dict[w].append(g)
    weeks = sorted(weeks_dict.items(), key=lambda x: x[0])

    return render(request, 'leagues/officials_hub.html', {
        'season': season,
        'budget_summary': budget_summary,
        'pool_members': pool_members,
        'candidate_officials': candidate_officials,
        'weeks': weeks,
    })


@login_required
def respond_official_assignment(request, assignment_id):
    """Official 1-tap confirmation or sub request ('Can't Make It')."""
    assignment = get_object_or_404(GameOfficialAssignment.objects.select_related('game', 'official', 'game__season'), id=assignment_id)
    if not (request.user.id == assignment.official_id or request.user.can_manage_league(assignment.game.season.league)):
        messages.error(request, "You do not have permission to respond to this assignment.")
        return redirect('home')

    action = request.POST.get('action') or request.GET.get('action')
    if action == 'confirm':
        assignment.status = 'confirmed'
        assignment.notes = ''
        assignment.save(update_fields=['status', 'notes'])
        messages.success(request, f"✓ Confirmed! You are officiating {assignment.game.team1.name} vs {assignment.game.team2.name}.")
    elif action == 'request_sub':
        notes = request.POST.get('notes', 'Needs sub')
        assignment.status = 'declined'
        assignment.notes = notes
        assignment.save(update_fields=['status', 'notes'])
        messages.warning(request, f"⚠️ Sub requested. This assignment is now open for pool members to claim.")

    next_url = request.POST.get('next') or request.GET.get('next')
    return redirect(next_url or 'home')


@login_required
def claim_official_assignment(request, assignment_id):
    """Pool member 1-tap claim for games needing a substitute official."""
    assignment = get_object_or_404(GameOfficialAssignment.objects.select_related('game', 'official', 'game__season'), id=assignment_id)
    season = assignment.game.season

    can_claim = (
        request.user in season.officials_pool.all() or
        request.user.role == 'referee' or
        request.user.can_manage_league(season.league)
    )
    if not can_claim:
        messages.error(request, "You must be in the approved officials pool to claim assignments.")
        return redirect('home')

    if assignment.status != 'declined':
        messages.info(request, "This assignment is already covered.")
        return redirect('home')

    old_official = assignment.official
    assignment.official = request.user
    assignment.status = 'confirmed'
    assignment.notes = f"Covered by {request.user.display_name} (subbed for {old_official.display_name})"
    assignment.save(update_fields=['official', 'status', 'notes'])
    season.officials_pool.add(request.user)

    messages.success(request, f"✋ You have claimed the assignment for {assignment.game}!")
    return redirect('home')


@login_required
def toggle_team_dues(request, team_id):
    """1-Tap Season Dues clearance toggle for League Commissioners."""
    team = get_object_or_404(Team.objects.select_related('league', 'season'), id=team_id)
    if not request.user.can_manage_league(team.league):
        messages.error(request, "Only League Commissioners can update team fee dues.")
        return redirect('season_detail', season_id=team.season_id)

    team.dues_paid = not team.dues_paid
    team.save(update_fields=['dues_paid'])

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok', 'dues_paid': team.dues_paid, 'team_name': team.name})

    status_str = "Paid ($" + str(team.season.registration_fee) + ")" if team.dues_paid else "Unpaid"
    messages.success(request, f"Updated dues for '{team.name}': {status_str}")
    return redirect('season_detail', season_id=team.season_id)


@login_required
def take_over_dugout_scoring(request, game_id):
    """Allows an authorized coach, referee, or commissioner to take over scoring lock."""
    game = get_object_or_404(Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'active_scorer'), id=game_id)
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


@login_required
@require_POST
def confirm_game_score(request, game_id):
    """1-Tap score confirmation by the opposing coach, referee, or commissioner."""
    game = get_object_or_404(Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'score_submitted_by'), id=game_id)
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


@login_required
@require_POST
def dispute_game_score(request, game_id):
    """Opposing coach or team representative flags score discrepancy for commissioner review."""
    game = get_object_or_404(Game.objects.select_related('season__league', 'team1__church', 'team2__church', 'score_submitted_by'), id=game_id)
    if not request.user.can_score_game(game):
        messages.error(request, "Permission denied: you cannot dispute scores for this match.")
        return redirect('game_detail', game_id=game.id)

    # Assigned official score lock check
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


@login_required
@require_POST
def resolve_score_dispute(request, game_id):
    """Commissioner-exclusive ruling resolving a disputed score."""
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


@login_required
@require_POST
def bulk_confirm_pending_scores(request):
    """Overall commissioner 1-tap approval of all pending scores."""
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


@login_required
@require_POST
def record_game_forfeit(request, game_id):
    """1-Tap Forfeit scoring assistant."""
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


@login_required
@require_POST
def toggle_official_payment(request, assignment_id):
    """1-Tap toggle for referee fee payment disbursement."""
    assignment = get_object_or_404(
        GameOfficialAssignment.objects.select_related('game__season__league', 'official'),
        id=assignment_id
    )
    league = assignment.game.season.league if assignment.game.season else None
    if not (request.user.is_overall_commissioner or (league and request.user.can_manage_league(league))):
        messages.error(request, "Only league commissioners can manage official fee disbursements.")
        return redirect('officials_hub', season_id=assignment.game.season_id)

    assignment.toggle_payment()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'status': 'ok',
            'pay_status': assignment.pay_status,
            'is_paid': assignment.pay_status == 'paid',
            'pay_amount': float(assignment.pay_amount)
        })

    status_label = "Paid" if assignment.pay_status == 'paid' else "Unpaid"
    messages.success(request, f"Updated payment status for {assignment.official.display_name} ({assignment.get_role_display()}): {status_label}")
    return redirect('officials_hub', season_id=assignment.game.season_id)


@login_required
def reschedule_rainouts(request, season_id):
    """Batch reschedule assistant for rained out / postponed games."""
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(season.league)):
        messages.error(request, "Only league commissioners can reschedule rainouts.")
        return redirect('season_detail', season_id=season.id)

    rainout_games = season.games.filter(status__in=['rainout', 'postponed']).select_related('team1', 'team2').order_by('date')

    if request.method == 'POST':
        game_ids = request.POST.getlist('selected_games')
        target_date_str = request.POST.get('target_date')
        target_time_str = request.POST.get('target_time', '18:00')
        interval_minutes = int(request.POST.get('interval_minutes', 60))

        if not target_date_str:
            messages.error(request, "Please choose a target makeup date.")
            return redirect('reschedule_rainouts', season_id=season.id)

        try:
            target_date = datetime.datetime.strptime(target_date_str, '%Y-%m-%d').date()
            time_parts = [int(p) for p in target_time_str.split(':')]
            start_time = datetime.time(time_parts[0], time_parts[1])
        except Exception:
            messages.error(request, "Invalid makeup date or time format.")
            return redirect('reschedule_rainouts', season_id=season.id)

        target_dt = datetime.datetime.combine(target_date, start_time)
        target_tz_dt = timezone.make_aware(target_dt, timezone.get_current_timezone())

        moved_count = 0
        current_slot = target_tz_dt
        for gid in game_ids:
            g = rainout_games.filter(id=gid).first()
            if g:
                g.date = current_slot
                g.status = 'scheduled'
                g.notes = (f"{g.notes or ''}\nRescheduled makeup for {current_slot.strftime('%b %d @ %I:%M %p')}").strip()
                g.save(update_fields=['date', 'status', 'notes'])
                current_slot += datetime.timedelta(minutes=interval_minutes)
                moved_count += 1

        messages.success(request, f"✓ Successfully rescheduled {moved_count} game(s) to {target_date.strftime('%A, %b %d, %Y')}.")
        return redirect('season_detail', season_id=season.id)

    return render(request, 'leagues/reschedule_rainouts.html', {
        'season': season,
        'rainout_games': rainout_games,
    })



@login_required
def manage_league_pools(request, league_id):
    """Console for League and Overall Commissioners to manage persistent venue and officials pools."""
    league = get_object_or_404(League, id=league_id)
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
        messages.error(request, "Permission denied: Only league commissioners can manage master pools.")
        return redirect('season_list', league_id=league_id)

    venues = league.venues.all().order_by('name')
    officials = league.master_officials_pool.all().order_by('first_name', 'last_name')
    
    available_users = CustomUser.objects.filter(is_active=True).exclude(
        id__in=officials.values_list('id', flat=True)
    ).order_by('first_name', 'last_name')[:40]

    return render(request, 'leagues/manage_pools.html', {
        'league': league,
        'venues': venues,
        'officials': officials,
        'available_users': available_users,
    })


@login_required
@require_POST
def add_league_venue(request, league_id):
    league = get_object_or_404(League, id=league_id)
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
        messages.error(request, "Permission denied.")
        return redirect('manage_league_pools', league_id=league_id)

    name = request.POST.get('name', '').strip()
    address = request.POST.get('address', '').strip()
    notes = request.POST.get('notes', '').strip()

    if not name:
        messages.error(request, "Venue / Field name is required.")
        return redirect('manage_league_pools', league_id=league_id)

    venue, created = LeagueVenue.objects.get_or_create(
        league=league,
        name=name,
        defaults={'address': address, 'notes': notes, 'is_active': True}
    )
    if created:
        messages.success(request, f"Venue '{venue.name}' added to master pool.")
    else:
        messages.info(request, f"Venue '{venue.name}' already exists in this league.")
    return redirect('manage_league_pools', league_id=league_id)


@login_required
@require_POST
def toggle_league_venue(request, league_id, venue_id):
    league = get_object_or_404(League, id=league_id)
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
        messages.error(request, "Permission denied.")
        return redirect('manage_league_pools', league_id=league_id)

    venue = get_object_or_404(LeagueVenue, id=venue_id, league=league)
    venue.is_active = not venue.is_active
    venue.save(update_fields=['is_active'])
    status_str = "active" if venue.is_active else "inactive / offline"
    messages.success(request, f"Venue '{venue.name}' marked {status_str}.")
    return redirect('manage_league_pools', league_id=league_id)


@login_required
@require_POST
def delete_league_venue(request, league_id, venue_id):
    league = get_object_or_404(League, id=league_id)
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
        messages.error(request, "Permission denied.")
        return redirect('manage_league_pools', league_id=league_id)

    venue = get_object_or_404(LeagueVenue, id=venue_id, league=league)
    venue_name = venue.name
    venue.delete()
    messages.success(request, f"Venue '{venue_name}' removed from league pool.")
    return redirect('manage_league_pools', league_id=league_id)


@login_required
@require_POST
def add_league_official(request, league_id):
    league = get_object_or_404(League, id=league_id)
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
        messages.error(request, "Permission denied.")
        return redirect('manage_league_pools', league_id=league_id)

    user_id = request.POST.get('user_id')
    user = get_object_or_404(CustomUser, id=user_id)
    league.master_officials_pool.add(user)
    messages.success(request, f"{user.display_name} added to {league.name} Master Officials Pool.")
    return redirect('manage_league_pools', league_id=league_id)


@login_required
@require_POST
def remove_league_official(request, league_id, user_id):
    league = get_object_or_404(League, id=league_id)
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
        messages.error(request, "Permission denied.")
        return redirect('manage_league_pools', league_id=league_id)

    user = get_object_or_404(CustomUser, id=user_id)
    league.master_officials_pool.remove(user)
    messages.success(request, f"{user.display_name} removed from {league.name} Master Officials Pool.")
    return redirect('manage_league_pools', league_id=league_id)


@login_required
def import_season_teams(request, season_id):
    """Allows League Commissioner to 1-tap re-use / import teams from an earlier season."""
    season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
    league = season.league
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
        messages.error(request, "Permission denied.")
        return redirect('season_detail', season_id=season_id)

    other_seasons = league.seasons.exclude(id=season.id).order_by('-start_date')
    selected_source_id = request.GET.get('source_season_id') or request.POST.get('source_season_id')
    source_season = None
    source_teams = []

    if selected_source_id:
        source_season = get_object_or_404(Season, id=selected_source_id, league=league)
        source_teams = source_season.teams.all().select_related('church', 'captain')

    if request.method == 'POST' and 'confirm_import' in request.POST:
        team_ids = request.POST.getlist('selected_teams')
        if not team_ids:
            messages.warning(request, "No teams selected for import.")
            return redirect(f"{request.path}?source_season_id={selected_source_id}")

        existing_names = set(season.teams.values_list('name', flat=True))
        imported_count = 0
        for st in source_season.teams.filter(id__in=team_ids):
            if st.name not in existing_names:
                Team.objects.create(
                    name=st.name,
                    league=league,
                    season=season,
                    church=st.church,
                    captain=st.captain,
                    team_color=st.team_color,
                    dues_paid=False,
                    default_lineup=st.default_lineup,
                )
                existing_names.add(st.name)
                imported_count += 1

        messages.success(request, f"Successfully imported {imported_count} team(s) into {season.name}.")
        return redirect('season_detail', season_id=season_id)

    return render(request, 'leagues/import_teams.html', {
        'season': season,
        'league': league,
        'other_seasons': other_seasons,
        'source_season': source_season,
        'source_teams': source_teams,
    })



# =====================================================================
# Phase 2: Disciplinary, Suspension & Incident Engine
# =====================================================================

@login_required
def manage_disciplinary_hub(request, league_id):
    """Commissioner and Committee interface to review incidents, issue suspensions, or ban participants."""
    league = get_object_or_404(League, id=league_id)
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
        messages.error(request, "Permission denied. Only League Commissioners can access Disciplinary Hub.")
        return redirect('season_list', league_id=league.id)

    records = PlayerDisciplinaryRecord.objects.filter(league=league).select_related('player', 'team', 'issued_by').order_by('-issued_at')
    active_records = [r for r in records if r.is_currently_active()]
    past_records = [r for r in records if not r.is_currently_active()]

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create_disciplinary_record':
            from users.models import CustomUser
            player_id = request.POST.get('player_id')
            team_id = request.POST.get('team_id') or None
            penalty_type = request.POST.get('penalty_type', 'game_count')
            reason = request.POST.get('reason', '').strip()
            games_count = int(request.POST.get('games_suspended_total', 1) or 1)
            suspended_until = request.POST.get('suspended_until') or None
            dues_forfeited = bool(request.POST.get('dues_forfeited'))

            player = get_object_or_404(CustomUser, id=player_id)
            team = Team.objects.filter(id=team_id, league=league).first() if team_id else None

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
                issued_by=request.user
            )

            if penalty_type == 'permanent_expulsion':
                player.is_expelled = True
                player.expulsion_reason = reason
                player.is_active = False
                player.save(update_fields=['is_expelled', 'expulsion_reason', 'is_active'])
                messages.warning(request, f"⛔ Participant {player.display_name} has been permanently expelled. Account deactivated.")
            else:
                messages.success(request, f"Recorded disciplinary action for {player.display_name}: {rec.get_penalty_type_display()}.")

            # League-wide notification
            if league.discord_webhook_url:
                send_discord_notification(
                    league.discord_webhook_url,
                    f"⚖️ League Disciplinary Notice ({league.name}): {player.display_name} issued {rec.get_penalty_type_display()}. Rationale: {reason}"
                )

            return redirect('manage_disciplinary_hub', league_id=league.id)

    # Participants eligible for discipline
    from users.models import CustomUser
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


@login_required
@require_POST
def reinstate_disciplinary_penalty(request, record_id):
    """Allows commissioner to rescind/lift an active suspension early."""
    record = get_object_or_404(PlayerDisciplinaryRecord.objects.select_related('league', 'player'), id=record_id)
    league = record.league
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
        messages.error(request, "Permission denied.")
        return redirect('manage_disciplinary_hub', league_id=league.id)

    notes = request.POST.get('reinstatement_notes', '').strip()
    record.status = 'rescinded'
    record.reinstated_at = timezone.now()
    record.resolution_notes = f"{record.resolution_notes}\n[RESCINDED by {request.user.display_name}]: {notes or 'Early reinstatement approved.'}".strip()
    record.save(update_fields=['status', 'reinstated_at', 'resolution_notes'])

    # If player was marked expelled, re-activate account
    if record.penalty_type == 'permanent_expulsion':
        record.player.is_expelled = False
        record.player.is_active = True
        record.player.save(update_fields=['is_expelled', 'is_active'])

    messages.success(request, f"✓ Lifted suspension for {record.player.display_name}. Player is reinstated.")
    return redirect('manage_disciplinary_hub', league_id=league.id)


@login_required
@require_POST
def report_game_incident(request, game_id):
    """Allows assigned official, umpire, or coach to report game conduct or ejections."""
    game = get_object_or_404(Game.objects.select_related('season__league', 'team1', 'team2'), id=game_id)
    if not request.user.can_score_game(game):
        messages.error(request, "Permission denied to report incident for this game.")
        return redirect('game_detail', game_id=game.id)

    from users.models import CustomUser
    player_id = request.POST.get('player_id')
    player = get_object_or_404(CustomUser, id=player_id)
    incident_type = request.POST.get('incident_type', 'misconduct')
    description = request.POST.get('description', '').strip()
    is_ejection = bool(request.POST.get('is_ejection'))

    team = game.team1 if player in game.team1.players.all() else game.team2

    # Log in game audit trail
    game.log_score_event(
        request.user,
        'incident_reported',
        f"Incident: {player.display_name} ({'EJECTION' if is_ejection else incident_type}): {description}"
    )

    # If ejection, automatically create 1-game auto-suspension pending commissioner review
    if is_ejection and game.season and game.season.league:
        PlayerDisciplinaryRecord.objects.create(
            player=player,
            league=game.season.league,
            team=team,
            game=game,
            penalty_type='game_count',
            status='active',
            games_suspended_total=1,
            reason=f"Game Ejection: {description}",
            issued_by=request.user
        )
        messages.warning(request, f"⚠️ Recorded ejection for {player.display_name}. 1-game suspension active pending committee review.")
    else:
        messages.info(request, f"Recorded conduct incident report for {player.display_name}.")

    return redirect('game_detail', game_id=game.id)


# =====================================================================
# Phase 3: Venue Condition Hotline & 1-Click Relocation
# =====================================================================

@login_required
@require_POST
def update_venue_status(request, venue_id):
    """Updates venue/field playability status (open, caution, closed, conflict, maintenance)."""
    venue = get_object_or_404(LeagueVenue.objects.select_related('league'), id=venue_id)
    league = venue.league
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
        messages.error(request, "Permission denied to update venue status.")
        return redirect('manage_league_pools', league_id=league.id)

    status = request.POST.get('status', 'open')
    status_note = request.POST.get('status_note', '').strip()
    venue.status = status
    venue.status_note = status_note
    venue.status_updated_by = request.user
    venue.save(update_fields=['status', 'status_note', 'status_updated_at', 'status_updated_by'])

    messages.success(request, f"Updated condition status for {venue.name}: {venue.get_status_display()}.")

    # Broadcast on discord if unplayable or relocated
    if status in ('closed', 'conflict') and league.discord_webhook_url:
        send_discord_notification(
            league.discord_webhook_url,
            f"📢 Field Alert ({league.name}): {venue.name} is {venue.get_status_display().upper()}. {status_note}"
        )

    return redirect(request.META.get('HTTP_REFERER') or 'home')


@login_required
@require_POST
def relocate_venue_games(request, venue_id):
    """1-Click atomic game relocator: moves scheduled games from one field to another or postpones them."""
    venue = get_object_or_404(LeagueVenue.objects.select_related('league'), id=venue_id)
    league = venue.league
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
        messages.error(request, "Permission denied.")
        return redirect('manage_league_pools', league_id=league.id)

    action_type = request.POST.get('action_type', 'relocate')  # 'relocate' or 'postpone'
    target_date_str = request.POST.get('target_date')  # YYYY-MM-DD
    new_venue_id = request.POST.get('new_venue_id')
    reason = request.POST.get('reason', '').strip()

    games_qs = Game.objects.filter(
        season__league=league,
        status='scheduled'
    ).filter(Q(venue=venue) | Q(location__icontains=venue.name))

    if target_date_str:
        try:
            target_date = timezone.datetime.strptime(target_date_str, '%Y-%m-%d').date()
            games_qs = games_qs.filter(date__date=target_date)
        except ValueError:
            pass

    games_list = list(games_qs)
    if not games_list:
        messages.warning(request, f"No scheduled games found at {venue.name} for the specified date.")
        return redirect('manage_league_pools', league_id=league.id)

    if action_type == 'relocate':
        new_venue = get_object_or_404(LeagueVenue, id=new_venue_id, league=league)
        for g in games_list:
            g.venue = new_venue
            g.location = new_venue.name
            g.save(update_fields=['venue', 'location'])
        messages.success(request, f"⚡ Successfully relocated {len(games_list)} game(s) from {venue.name} to {new_venue.name}.")
        if league.discord_webhook_url:
            send_discord_notification(
                league.discord_webhook_url,
                f"🚨 Field Relocation Alert: {len(games_list)} game(s) originally at {venue.name} moved to {new_venue.name}. Reason: {reason or 'Field conditions'}"
            )
    else:  # postpone
        for g in games_list:
            g.status = 'postponed'
            g.notes = f"{g.notes}\n[POSTPONED]: {reason or 'Field closed due to weather/conflict'}".strip()
            g.save(update_fields=['status', 'notes'])
        messages.success(request, f"🌧️ Postponed {len(games_list)} game(s) at {venue.name}.")
        if league.discord_webhook_url:
            send_discord_notification(
                league.discord_webhook_url,
                f"🌧️ Weather Postponement: All games at {venue.name} postponed. Reason: {reason or 'Unplayable conditions'}"
            )

    return redirect('manage_league_pools', league_id=league.id)


# =====================================================================
# Phase 4 & 5: Sportsmanship & Season Renewal Evaluations
# =====================================================================

@login_required
@require_POST
def submit_sportsmanship_rating(request, game_id):
    """Submits 1-5 star fellowship, referee respect, and bench decorum scores for a team."""
    game = get_object_or_404(Game.objects.select_related('season__league', 'team1', 'team2'), id=game_id)
    rated_team_id = request.POST.get('rated_team_id')
    rated_team = get_object_or_404(Team, id=rated_team_id)

    # Determine evaluator role
    is_official = (
        request.user.role == 'referee' or
        hasattr(game, 'official_assignments') and game.official_assignments.filter(official=request.user).exists()
    )
    is_commish = request.user.is_overall_commissioner or (game.season and request.user.can_manage_league(game.season.league))
    is_coach = (game.team1.captain_id == request.user.id or game.team2.captain_id == request.user.id)

    if not (is_official or is_commish or is_coach):
        messages.error(request, "Permission denied to evaluate sportsmanship for this match.")
        return redirect('game_detail', game_id=game.id)

    if is_official:
        role = 'official'
    elif is_commish:
        role = 'commissioner'
    else:
        role = 'coach'

    try:
        score = max(1, min(5, int(request.POST.get('score', 5))))
        respect = max(1, min(5, int(request.POST.get('respect_for_officials', 5))))
        bench = max(1, min(5, int(request.POST.get('bench_conduct', 5))))
    except (ValueError, TypeError):
        score, respect, bench = 5, 5, 5

    notes = request.POST.get('notes', '').strip()

    rating, created = GameSportsmanshipRating.objects.update_or_create(
        game=game,
        evaluator=request.user,
        rated_team=rated_team,
        defaults={
            'evaluator_role': role,
            'score': score,
            'respect_for_officials': respect,
            'bench_conduct': bench,
            'notes': notes,
        }
    )

    messages.success(request, f"✓ Thank you! Sportsmanship rating ({score}★) recorded for {rated_team.name}.")
    return redirect('game_detail', game_id=game.id)


@login_required
def manage_sportsmanship_dashboard(request, league_id):
    """League Committee dashboard reviewing team fellowship scores and customizable renewal thresholds."""
    league = get_object_or_404(League, id=league_id)
    if not (request.user.is_overall_commissioner or request.user.can_manage_league(league)):
        messages.error(request, "Permission denied.")
        return redirect('season_list', league_id=league.id)

    if request.method == 'POST' and 'update_thresholds' in request.POST:
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

    teams = league.teams.all().select_related('church', 'captain', 'season')
    teams_summary = []
    for t in teams:
        summary = t.get_sportsmanship_summary()
        summary['team'] = t
        teams_summary.append(summary)

    # Sort lowest scores first so problem teams are immediately visible to committee
    teams_summary.sort(key=lambda s: (s['avg_score'], s['count']))

    return render(request, 'leagues/sportsmanship_dashboard.html', {
        'league': league,
        'teams_summary': teams_summary,
    })
