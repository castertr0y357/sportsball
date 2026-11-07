from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from .models import Church, Announcement
from .forms import ChurchForm, AnnouncementForm
from leagues.models import League, Season, Game, Team, GameOfficialAssignment
from users.models import CustomUser
from core.services.notifications import send_discord_notification, send_twilio_sms


def home(request):
    today = timezone.localdate()
    now = timezone.now()

    urgent_alerts = Announcement.objects.filter(is_urgent=True)[:3]
    recent_announcements = Announcement.objects.select_related('league', 'season', 'author')[:4]
    devotional = Announcement.objects.filter(category='devotional').first()
    active_seasons = Season.objects.filter(current=True).select_related('league')

    # 1. Games currently in progress (Live Now)
    live_games = Game.objects.filter(
        status='in_progress'
    ).select_related('team1', 'team2', 'season__league').order_by('date')

    # 2. Games scheduled for today
    today_games = Game.objects.filter(
        status='scheduled',
        date__date=today
    ).select_related('team1', 'team2', 'season__league').order_by('date')

    # 3. Personalized next game for authenticated players / coaches
    my_next_game = None
    my_next_game_rsvp = None
    my_team = None
    can_manage_next_lineup = False
    next_game_rsvp_summary = None

    if request.user.is_authenticated:
        my_next_game = Game.objects.filter(
            Q(team1__players=request.user) | Q(team2__players=request.user) |
            Q(team1__captain=request.user) | Q(team2__captain=request.user),
            status='scheduled',
            date__gte=now
        ).select_related('team1__church', 'team2__church', 'season__league').order_by('date').first()

        if my_next_game:
            my_next_game_rsvp = my_next_game.get_player_rsvp(request.user)
            if my_next_game.team1.players.filter(id=request.user.id).exists() or my_next_game.team1.captain_id == request.user.id:
                my_team = my_next_game.team1
            else:
                my_team = my_next_game.team2

            can_manage_next_lineup = (
                request.user == my_team.captain or
                request.user.can_manage_church(my_team.church) or
                request.user.can_manage_league(my_next_game.season.league) or
                request.user.is_overall_commissioner
            )
            next_game_rsvp_summary = my_next_game.get_team_rsvp_summary(my_team)

    # 4. Upcoming scheduled matchups & Recent Results - scoped to rostered players, confirmed subs, or coaches
    user_has_team_or_sub = False
    see_all_schedule_url = None
    upcoming_games = []
    recent_results = []

    if request.user.is_authenticated:
        user_teams = request.user.teams.all()
        captained_teams = request.user.captained_teams.all()

        confirmed_sub_game_ids = set(
            request.user.officiating_assignments.filter(status='confirmed', game__date__gte=now)
            .values_list('game_id', flat=True)
        )
        subbed_game_ids = set(
            request.user.lineup_appearances.filter(game__date__gte=now, is_present=True)
            .values_list('game_id', flat=True)
        )
        all_sub_game_ids = confirmed_sub_game_ids.union(subbed_game_ids)

        is_assigned_to_team = user_teams.exists() or captained_teams.exists()
        is_confirmed_sub = bool(all_sub_game_ids)
        is_staff_or_commish = request.user.can_manage_teams or request.user.is_league_admin

        user_has_team_or_sub = is_assigned_to_team or is_confirmed_sub or is_staff_or_commish

        if user_has_team_or_sub:
            if is_assigned_to_team or is_confirmed_sub:
                upcoming_games = Game.objects.filter(
                    Q(team1__in=user_teams) | Q(team2__in=user_teams) |
                    Q(team1__in=captained_teams) | Q(team2__in=captained_teams) |
                    Q(id__in=all_sub_game_ids),
                    status='scheduled',
                    date__date__gt=today
                ).select_related('team1', 'team2', 'season__league').order_by('date')[:5]

                recent_results = Game.objects.filter(
                    Q(team1__in=user_teams) | Q(team2__in=user_teams) |
                    Q(team1__in=captained_teams) | Q(team2__in=captained_teams) |
                    Q(id__in=all_sub_game_ids),
                    status='completed'
                ).select_related('team1', 'team2', 'season__league').order_by('-date')[:5]
            else:
                upcoming_games = Game.objects.filter(
                    status='scheduled',
                    date__date__gt=today
                ).select_related('team1', 'team2', 'season__league').order_by('date')[:5]

                recent_results = Game.objects.filter(
                    status='completed'
                ).select_related('team1', 'team2', 'season__league').order_by('-date')[:5]

            if my_team and my_team.season_id:
                see_all_schedule_url = reverse('schedule_grid', args=[my_team.season_id])
            elif active_seasons.exists():
                see_all_schedule_url = reverse('schedule_grid', args=[active_seasons.first().id])
            else:
                see_all_schedule_url = reverse('league_list')

    churches_count = Church.objects.count()
    leagues_count = League.objects.count()

    # 6. Officials & Referees Assignments
    my_officiating_assignments = []
    open_sub_assignments = []
    executive_stats = None

    if request.user.is_authenticated:
        my_officiating_assignments = request.user.officiating_assignments.select_related(
            'game__team1', 'game__team2', 'game__season__league'
        ).filter(game__date__gte=now - timezone.timedelta(hours=4)).order_by('game__date')[:5]

        # Open sub claims board
        if (
            request.user.role in ['referee', 'admin', 'church_admin', 'coach']
            or request.user.is_overall_commissioner
            or request.user.officiating_assignments.exists()
            or request.user.officiating_seasons.exists()
        ):
            open_sub_assignments = GameOfficialAssignment.objects.filter(
                status='declined',
                game__date__gte=now
            ).select_related('game__team1', 'game__team2', 'game__season__league', 'official').order_by('game__date')[:6]

        if request.user.is_overall_commissioner:
            unpaid_teams_count = Team.objects.filter(dues_paid=False, season__current=True).count()
            rainouts_today = Game.objects.filter(date__date=today, status__in=['rainout', 'postponed']).count()
            pending_waivers_count = CustomUser.objects.filter(waiver_signed=False).count()
            executive_stats = {
                'churches_count': churches_count,
                'active_seasons_count': active_seasons.count(),
                'unpaid_teams_count': unpaid_teams_count,
                'rainouts_today': rainouts_today,
                'pending_waivers_count': pending_waivers_count,
            }

    return render(request, 'core/home.html', {
        'urgent_alerts': urgent_alerts,
        'recent_announcements': recent_announcements,
        'devotional': devotional,
        'active_seasons': active_seasons,
        'live_games': live_games,
        'today_games': today_games,
        'my_next_game': my_next_game,
        'my_next_game_rsvp': my_next_game_rsvp,
        'my_team': my_team,
        'can_manage_next_lineup': can_manage_next_lineup,
        'next_game_rsvp_summary': next_game_rsvp_summary,
        'upcoming_games': upcoming_games,
        'recent_results': recent_results,
        'churches_count': churches_count,
        'leagues_count': leagues_count,
        'today': today,
        'user_has_team_or_sub': user_has_team_or_sub,
        'see_all_schedule_url': see_all_schedule_url,
        'my_officiating_assignments': my_officiating_assignments,
        'open_sub_assignments': open_sub_assignments,
        'executive_stats': executive_stats,
    })


@login_required
def my_church(request):
    """
    Dedicated congregation hub for authenticated members.
    - If user manages a church as Church Commissioner, routes to that church hub with management tools.
    - If user belongs to a home church, routes to their church hub.
    - If user has not selected a church, prompts them to select their home congregation.
    """
    user = request.user
    managed_church = user.managed_churches.first()
    if managed_church:
        return redirect('church_detail', church_id=managed_church.id)

    if user.church:
        return redirect('church_detail', church_id=user.church_id)

    if request.method == 'POST':
        church_id = request.POST.get('church_id')
        if church_id:
            church = get_object_or_404(Church, id=church_id)
            user.church = church
            user.save(update_fields=['church'])
            messages.success(request, f"Welcome to {church.name}! You are now affiliated with this congregation.")
            return redirect('church_detail', church_id=church.id)
        else:
            messages.info(request, "You are participating as an outreach or community guest.")
            return redirect('home')

    churches = Church.objects.order_by('name')
    return render(request, 'core/select_church.html', {'churches': churches})


def church_list(request):
    """Partner Churches Directory - accessible by League Admins & Commissioners."""
    if not request.user.is_authenticated:
        return redirect('home')

    if not request.user.is_league_admin:
        messages.info(request, "The master church directory is reserved for league commissioners. Here is your congregation hub.")
        return redirect('my_church')

    churches = Church.objects.select_related('commissioner').prefetch_related('teams', 'members').all()
    return render(request, 'core/church_list.html', {'churches': churches})


def church_detail(request, church_id):
    church = get_object_or_404(
        Church.objects.select_related('commissioner').prefetch_related('members'),
        id=church_id
    )
    teams = church.teams.select_related('league', 'season', 'captain').prefetch_related('players').all()
    members = church.members.all()

    is_church_commish = (
        request.user.is_authenticated and
        request.user.can_manage_church(church)
    )
    is_overall_commish = (
        request.user.is_authenticated and
        request.user.is_overall_commissioner
    )

    open_seasons = Season.objects.filter(registration_open=True, current=True).select_related('league')
    eligible_commissioners = CustomUser.objects.filter(
        Q(church=church) | Q(role__in=['admin', 'committee', 'church_admin', 'coach'])
    ).distinct().order_by('first_name', 'last_name')

    can_view_members = (
        request.user.is_authenticated and (
            is_church_commish or
            is_overall_commish or
            request.user.is_league_admin or
            request.user.church_id == church.id
        )
    )

    church_invite_url = church.get_invite_url(request)

    church_games = Game.objects.filter(
        Q(team1__church=church) | Q(team2__church=church)
    ).select_related('team1', 'team2', 'season__league').order_by('date')[:15]

    return render(request, 'core/church_detail.html', {
        'church': church,
        'teams': teams,
        'members': members,
        'is_church_commish': is_church_commish,
        'is_overall_commish': is_overall_commish,
        'can_view_members': can_view_members,
        'open_seasons': open_seasons,
        'eligible_commissioners': eligible_commissioners,
        'church_invite_url': church_invite_url,
        'church_games': church_games,
    })


@login_required
def assign_church_commissioner(request, church_id):
    """Allows Overall Commissioner to designate the Church Commissioner for a church."""
    church = get_object_or_404(Church, id=church_id)
    if not request.user.is_overall_commissioner:
        messages.error(request, "Only Overall Commissioners can assign Church Commissioners.")
        return redirect('church_detail', church_id=church.id)

    if request.method == 'POST':
        user_id = request.POST.get('commissioner_id')
        if user_id:
            new_commish = get_object_or_404(CustomUser, id=user_id)
            church.commissioner = new_commish
            church.save(update_fields=['commissioner'])
            if new_commish.role in ('player', 'coach'):
                new_commish.role = 'church_admin'
                new_commish.save(update_fields=['role'])
            messages.success(request, f"{new_commish.display_name} is now the Church Commissioner for {church.name}!")
        else:
            church.commissioner = None
            church.save(update_fields=['commissioner'])
            messages.info(request, f"Removed designated commissioner for {church.name}.")

    return redirect('church_detail', church_id=church.id)


@login_required
def toggle_church_dues(request, church_id):
    """Allows Overall Commissioner to toggle church affiliation dues status."""
    church = get_object_or_404(Church, id=church_id)
    if not request.user.is_overall_commissioner:
        messages.error(request, "Only Overall Commissioners can update church dues status.")
        return redirect('church_detail', church_id=church.id)

    if request.method == 'POST':
        church.dues_paid = not church.dues_paid
        church.save(update_fields=['dues_paid'])
        status_label = "Paid / Current" if church.dues_paid else "Pending / Unpaid"
        messages.success(request, f"Updated {church.name} league dues to: {status_label}")

    return redirect('church_detail', church_id=church.id)


@login_required
def create_church(request):
    if not request.user.is_overall_commissioner:
        messages.error(request, "Only Overall Commissioners can add partner churches.")
        return redirect('home')
    if request.method == 'POST':
        form = ChurchForm(request.POST)
        if form.is_valid():
            church = form.save()
            messages.success(request, f"Church '{church.name}' added to the directory.")
            return redirect('church_detail', church_id=church.id)
    else:
        form = ChurchForm()
    return render(request, 'core/church_form.html', {'form': form})


def announcement_list(request):
    announcements = Announcement.objects.select_related('league', 'season', 'author').all()
    return render(request, 'core/announcement_list.html', {'announcements': announcements})


@login_required
def create_announcement(request):
    if not request.user.can_manage_teams:
        messages.error(request, "Only league admins and coaches can post league announcements.")
        return redirect('announcement_list')

    if request.method == 'POST':
        form = AnnouncementForm(request.POST, user=request.user)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.author = request.user
            if not (request.user.is_overall_commissioner or request.user.is_league_admin):
                announcement.is_urgent = False
            announcement.save()
            # Broadcast to Discord if configured
            if announcement.send_discord:
                webhook = None
                if announcement.season and announcement.season.discord_webhook_url:
                    webhook = announcement.season.discord_webhook_url
                elif announcement.league and announcement.league.discord_webhook_url:
                    webhook = announcement.league.discord_webhook_url
                if webhook:
                    send_discord_notification(webhook, announcement.title, announcement.content)
            messages.success(request, "Announcement published.")
            return redirect('announcement_list')
    else:
        form = AnnouncementForm(user=request.user)
    return render(request, 'core/create_announcement.html', {'form': form})

def join_church_by_invite(request, invite_code):
    """1-Click Onboarding Link for Partner Church Pastors and Sports Directors."""
    church = get_object_or_404(Church, invite_code=invite_code)

    if not request.user.is_authenticated:
        from django.urls import reverse
        return redirect(f"{reverse('register')}?church_invite={invite_code}")

    # Designate user as Church Commissioner
    church.commissioner = request.user
    church.save(update_fields=['commissioner'])
    if request.user.role in ('player', 'coach'):
        request.user.role = 'church_admin'
    request.user.church = church
    request.user.save(update_fields=['role', 'church'])

    messages.success(
        request,
        f"Welcome, {request.user.first_name}! You are now appointed as Church Commissioner for {church.name}."
    )
    return redirect('church_detail', church_id=church.id)
