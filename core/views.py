from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from .models import Church, Announcement
from .forms import ChurchForm, AnnouncementForm
from leagues.models import League, Season, Game
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
            Q(team1__players=request.user) | Q(team2__players=request.user) |
            Q(team1__captain=request.user) | Q(team2__captain=request.user),
            status__in=['scheduled', 'in_progress'],
            date__gte=now - timezone.timedelta(hours=4)
        ).select_related('team1', 'team2', 'season__league').order_by('date').first()

    # 4. Next upcoming games (next 5)
    upcoming_games = Game.objects.filter(
        status='scheduled',
        date__gte=now - timezone.timedelta(hours=2)
    ).select_related('team1', 'team2', 'season__league').order_by('date')[:5]

    # 5. Recent completed game results
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


def church_list(request):
    churches = Church.objects.prefetch_related('teams', 'members').all()
    return render(request, 'core/church_list.html', {'churches': churches})


def church_detail(request, church_id):
    church = get_object_or_404(Church, id=church_id)
    teams = church.teams.select_related('league', 'season', 'captain').all()
    members = church.members.all()
    return render(request, 'core/church_detail.html', {
        'church': church,
        'teams': teams,
        'members': members,
    })


@login_required
def create_church(request):
    if not request.user.can_manage_teams:
        messages.error(request, "Only league admins or coaches can add partner churches.")
        return redirect('church_list')
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
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.author = request.user
            announcement.save()

            if announcement.is_urgent:
                webhook_url = getattr(announcement.season, 'discord_webhook_url', '') if announcement.season else ''
                if webhook_url:
                    send_discord_notification(
                        webhook_url,
                        title=f"🚨 URGENT ALERT: {announcement.title}",
                        description=announcement.content,
                        color=0xd97706
                    )

            messages.success(request, f"Announcement '{announcement.title}' posted successfully.")
            return redirect('announcement_list')
    else:
        form = AnnouncementForm()
    return render(request, 'core/announcement_form.html', {'form': form})
