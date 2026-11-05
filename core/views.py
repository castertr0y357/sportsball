from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Church, Announcement
from .forms import ChurchForm, AnnouncementForm
from leagues.models import League, Season, Game
from core.services.notifications import send_discord_notification, send_twilio_sms


def home(request):
    urgent_alerts = Announcement.objects.filter(is_urgent=True)[:3]
    recent_announcements = Announcement.objects.select_related('league', 'season', 'author')[:5]
    devotional = Announcement.objects.filter(category='devotional').first()
    active_seasons = Season.objects.filter(current=True).select_related('league')
    upcoming_games = Game.objects.filter(status='scheduled').select_related('team1', 'team2', 'season__league').order_by('date')[:6]
    recent_results = Game.objects.filter(status='completed').select_related('team1', 'team2', 'season__league').order_by('-date')[:6]
    churches_count = Church.objects.count()
    leagues_count = League.objects.count()

    return render(request, 'core/home.html', {
        'urgent_alerts': urgent_alerts,
        'recent_announcements': recent_announcements,
        'devotional': devotional,
        'active_seasons': active_seasons,
        'upcoming_games': upcoming_games,
        'recent_results': recent_results,
        'churches_count': churches_count,
        'leagues_count': leagues_count,
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
    category = request.GET.get('category', '')
    announcements = Announcement.objects.select_related('league', 'season', 'author').all()
    if category:
        announcements = announcements.filter(category=category)
    return render(request, 'core/announcement_list.html', {
        'announcements': announcements,
        'selected_category': category,
        'categories': Announcement.CATEGORY_CHOICES,
    })


@login_required
def create_announcement(request):
    if not request.user.can_manage_teams:
        messages.error(request, "You don't have permission to post announcements.")
        return redirect('announcement_list')
    if request.method == 'POST':
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.author = request.user
            announcement.save()

            # Automatic Discord Webhook & Optional SMS Notification
            webhook = ''
            if announcement.season and announcement.season.discord_webhook_url:
                webhook = announcement.season.discord_webhook_url
            elif announcement.league and announcement.league.discord_webhook_url:
                webhook = announcement.league.discord_webhook_url

            if webhook:
                color = 0xdc2626 if announcement.is_urgent else 0x1e3a8a
                send_discord_notification(
                    webhook_url=webhook,
                    title=f"[{announcement.get_category_display()}] {announcement.title}",
                    description=announcement.content,
                    color=color
                )

            messages.success(request, f"Announcement '{announcement.title}' published.")
            return redirect('announcement_list')
    else:
        form = AnnouncementForm()
    return render(request, 'core/announcement_form.html', {'form': form})
