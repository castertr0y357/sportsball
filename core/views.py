from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from .models import Church, Announcement
from .forms import ChurchForm, AnnouncementForm
from leagues.models import League, Season, Game, Team
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
    if request.user.is_authenticated:
        my_next_game = Game.objects.filter(
            Q(team1__players=request.user) | Q(team2__players=request.user),
            status='scheduled',
            date__gte=now
        ).select_related('team1', 'team2', 'season__league').order_by('date').first()

    # 4. Upcoming scheduled matchups (future days)
    upcoming_games = Game.objects.filter(
        status='scheduled',
        date__date__gt=today
    ).select_related('team1', 'team2', 'season__league').order_by('date')[:5]

    # 5. Recent completed scores
    recent_results = Game.objects.filter(
        status='completed'
    ).select_related('team1', 'team2', 'season__league').order_by('-date')[:5]

    churches_count = Church.objects.count()
    leagues_count = League.objects.count()

    return render(request, 'core/home.html', {
        'urgent_alerts': urgent_alerts,
        'recent_announcements': recent_announcements,
        'devotional': devotional,
        'active_seasons': active_seasons,
        'live_games': live_games,
        'today_games': today_games,
        'my_next_game': my_next_game,
        'upcoming_games': upcoming_games,
        'recent_results': recent_results,
        'churches_count': churches_count,
        'leagues_count': leagues_count,
        'today': today,
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

    return render(request, 'core/church_detail.html', {
        'church': church,
        'teams': teams,
        'members': members,
        'is_church_commish': is_church_commish,
        'is_overall_commish': is_overall_commish,
        'can_view_members': can_view_members,
        'open_seasons': open_seasons,
        'eligible_commissioners': eligible_commissioners,
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
