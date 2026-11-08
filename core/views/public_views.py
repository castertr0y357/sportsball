"""
Class-Based Views for Home Dashboard, Announcements, and Church Partner Directories.
"""

from __future__ import annotations
from datetime import date
from typing import Any
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import View, ListView, DetailView, CreateView
from core.models import Church, Announcement
from core.forms import ChurchForm, AnnouncementForm
from leagues.models import League, Season, Game, Team, GameOfficialAssignment, LeagueVenue
from users.models import CustomUser
from core.services.notifications import send_discord_notification, send_twilio_sms


class HomeView(View):
    """Personalized home feed displaying in-progress games, daily matches, RSVPs, and alerts."""

    def get(self, request):
        today = timezone.localdate()
        now = timezone.now()

        urgent_alerts = Announcement.objects.filter(is_urgent=True)[:3]
        recent_announcements = Announcement.objects.select_related('league', 'season', 'author')[:4]
        devotional = Announcement.objects.filter(category='devotional').first()
        active_seasons = Season.objects.filter(current=True).select_related('league')

        live_games = Game.objects.filter(
            status='in_progress'
        ).select_related('team1', 'team2', 'season__league').order_by('date')

        today_games = Game.objects.filter(
            status='scheduled',
            date__date=today
        ).select_related('team1', 'team2', 'season__league').order_by('date')

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

                    primary_team = captained_teams.first() or user_teams.first()
                    if primary_team:
                        see_all_schedule_url = reverse('team_detail', args=[primary_team.id])
                else:
                    upcoming_games = Game.objects.filter(
                        status='scheduled',
                        date__date__gt=today
                    ).select_related('team1', 'team2', 'season__league').order_by('date')[:5]

                    current_season = active_seasons.first()
                    if current_season:
                        see_all_schedule_url = reverse('schedule_grid', args=[current_season.id])

                recent_results = Game.objects.filter(
                    status='completed'
                ).select_related('team1', 'team2', 'season__league').order_by('-date')[:4]

        my_officiating_assignments = []
        open_sub_assignments = []
        if request.user.is_authenticated:
            my_officiating_assignments = GameOfficialAssignment.objects.filter(
                official=request.user,
                game__date__gte=now - timezone.timedelta(hours=4)
            ).select_related('game__team1', 'game__team2', 'game__season__league').order_by('game__date')[:5]

            can_claim_subs = (
                request.user.role == 'referee' or
                request.user.is_overall_commissioner or
                Season.objects.filter(officials_pool=request.user).exists()
            )
            if can_claim_subs:
                open_sub_assignments = GameOfficialAssignment.objects.filter(
                    status='declined',
                    game__date__gte=now
                ).select_related('game__team1', 'game__team2', 'official', 'game__season').order_by('game__date')[:5]

        pending_score_confirmations = []
        if request.user.is_authenticated:
            if request.user.is_overall_commissioner:
                pending_score_confirmations = Game.objects.filter(
                    status='pending_confirmation'
                ).select_related('team1', 'team2', 'season__league', 'score_submitted_by')[:6]
            else:
                user_captain_teams = request.user.captained_teams.all()
                if user_captain_teams.exists():
                    pending_score_confirmations = Game.objects.filter(
                        Q(team1__in=user_captain_teams) | Q(team2__in=user_captain_teams),
                        status='pending_confirmation'
                    ).exclude(score_submitted_by=request.user).select_related('team1', 'team2', 'season__league', 'score_submitted_by')[:6]

        executive_stats = None
        if request.user.is_authenticated and (request.user.is_overall_commissioner or request.user.is_league_admin):
            executive_stats = {
                'total_players': CustomUser.objects.count(),
                'active_teams': Team.objects.count(),
                'total_churches': Church.objects.count(),
                'pending_scores_count': Game.objects.filter(status='pending_confirmation').count(),
                'open_sub_count': GameOfficialAssignment.objects.filter(status='declined', game__date__gte=now).count(),
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
            'user_has_team_or_sub': user_has_team_or_sub,
            'see_all_schedule_url': see_all_schedule_url,
            'my_officiating_assignments': my_officiating_assignments,
            'open_sub_assignments': open_sub_assignments,
            'pending_score_confirmations': pending_score_confirmations,
            'executive_stats': executive_stats,
            'active_venues': LeagueVenue.objects.filter(is_active=True).select_related('league')[:8],
        })


class MyChurchView(LoginRequiredMixin, View):
    """Dedicated congregation hub routing for authenticated church members."""

    def get(self, request):
        user = request.user
        managed_church = user.managed_churches.first()
        if managed_church:
            return redirect('church_detail', church_id=managed_church.id)

        if user.church:
            return redirect('church_detail', church_id=user.church_id)

        churches = Church.objects.order_by('name')
        return render(request, 'core/select_church.html', {'churches': churches})

    def post(self, request):
        user = request.user
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


class ChurchListView(View):
    """Partner Churches Directory - accessible by League Admins & Commissioners."""

    def get(self, request):
        if not request.user.is_authenticated:
            return redirect('home')

        if not request.user.is_league_admin:
            messages.info(request, "The master church directory is reserved for league commissioners. Here is your congregation hub.")
            return redirect('my_church')

        churches = Church.objects.select_related('commissioner').prefetch_related('teams', 'members').all()
        return render(request, 'core/church_list.html', {'churches': churches})


class ChurchDetailView(View):
    """Congregation hub displaying registered church teams, roster members, and upcoming matches."""

    def get(self, request, church_id: int):
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


class AssignChurchCommissionerView(LoginRequiredMixin, View):
    """Allows Overall Commissioner to designate the Church Commissioner for a church."""

    def post(self, request, church_id: int):
        church = get_object_or_404(Church, id=church_id)
        if not request.user.is_overall_commissioner:
            messages.error(request, "Only Overall Commissioners can assign Church Commissioners.")
            return redirect('church_detail', church_id=church.id)

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


class ToggleChurchDuesView(LoginRequiredMixin, View):
    """Allows Overall Commissioner to toggle church affiliation dues status."""

    def post(self, request, church_id: int):
        church = get_object_or_404(Church, id=church_id)
        if not request.user.is_overall_commissioner:
            messages.error(request, "Only Overall Commissioners can update church dues status.")
            return redirect('church_detail', church_id=church.id)

        church.dues_paid = not church.dues_paid
        church.save(update_fields=['dues_paid'])
        status_label = "Paid / Current" if church.dues_paid else "Pending / Unpaid"
        messages.success(request, f"Updated {church.name} league dues to: {status_label}")
        return redirect('church_detail', church_id=church.id)


class CreateChurchView(LoginRequiredMixin, View):
    """Allows Overall Commissioner to establish a new partner congregation."""

    def get(self, request):
        if not request.user.is_overall_commissioner:
            messages.error(request, "Only Overall Commissioners can add partner churches.")
            return redirect('home')
        form = ChurchForm()
        return render(request, 'core/church_form.html', {'form': form})

    def post(self, request):
        if not request.user.is_overall_commissioner:
            messages.error(request, "Only Overall Commissioners can add partner churches.")
            return redirect('home')
        form = ChurchForm(request.POST)
        if form.is_valid():
            church = form.save()
            messages.success(request, f"Church '{church.name}' added to the directory.")
            return redirect('church_detail', church_id=church.id)
        return render(request, 'core/church_form.html', {'form': form})


class AnnouncementListView(View):
    """Public listing of league and devotional announcements."""

    def get(self, request):
        announcements = Announcement.objects.select_related('league', 'season', 'author').all()
        return render(request, 'core/announcement_list.html', {'announcements': announcements})


class CreateAnnouncementView(LoginRequiredMixin, View):
    """Publishes announcements and sends Discord / SMS notifications."""

    def get(self, request):
        if not request.user.can_manage_teams:
            messages.error(request, "Only league admins and coaches can post league announcements.")
            return redirect('announcement_list')
        form = AnnouncementForm(user=request.user)
        return render(request, 'core/create_announcement.html', {'form': form})

    def post(self, request):
        if not request.user.can_manage_teams:
            messages.error(request, "Only league admins and coaches can post league announcements.")
            return redirect('announcement_list')

        form = AnnouncementForm(request.POST, user=request.user)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.author = request.user
            if not (request.user.is_overall_commissioner or request.user.is_league_admin):
                announcement.is_urgent = False
            announcement.save()

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

        return render(request, 'core/create_announcement.html', {'form': form})


class JoinChurchByInviteView(View):
    """1-Click Onboarding Link for Partner Church Pastors and Sports Directors."""

    def get(self, request, invite_code: str):
        church = get_object_or_404(Church, invite_code=invite_code)
        if not request.user.is_authenticated:
            return redirect(f"{reverse('register')}?church_invite={invite_code}")

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


class AnnouncementDetailView(View):
    """Individual announcement view with management actions."""

    def get(self, request, pk: int):
        announcement = get_object_or_404(
            Announcement.objects.select_related('league', 'season', 'author'),
            pk=pk
        )
        can_manage = request.user.is_authenticated and (
            request.user.is_overall_commissioner or
            request.user.is_league_admin or
            request.user == announcement.author
        )
        return render(request, 'core/announcement_detail.html', {
            'announcement': announcement,
            'can_manage': can_manage,
        })


class ToggleAnnouncementBannerView(LoginRequiredMixin, View):
    """Toggles top-of-page emergency banner status for an announcement."""

    def post(self, request, pk: int):
        announcement = get_object_or_404(Announcement, pk=pk)
        if not (request.user.is_overall_commissioner or request.user.is_league_admin):
            messages.error(request, "Only league commissioners can toggle alert banners.")
            return redirect('announcement_detail', pk=pk)

        if not announcement.is_banner:
            announcement.is_banner = True
            announcement.banner_active = True
        else:
            announcement.banner_active = not announcement.banner_active
        announcement.save(update_fields=['is_banner', 'banner_active'])

        status_str = "activated as top alert banner" if announcement.banner_active else "deactivated from alert banner"
        messages.success(request, f"Announcement {status_str}.")
        return redirect('announcement_detail', pk=pk)


# ============================================================================
# Callable view functions for backwards compatibility
# ============================================================================
home = HomeView.as_view()
my_church = MyChurchView.as_view()
church_list = ChurchListView.as_view()
church_detail = ChurchDetailView.as_view()
create_church = CreateChurchView.as_view()
assign_church_commissioner = AssignChurchCommissionerView.as_view()
toggle_church_dues = ToggleChurchDuesView.as_view()
announcement_list = AnnouncementListView.as_view()
create_announcement = CreateAnnouncementView.as_view()
join_church_by_invite = JoinChurchByInviteView.as_view()
announcement_detail = AnnouncementDetailView.as_view()
toggle_announcement_banner = ToggleAnnouncementBannerView.as_view()


class HealthCheckView(View):
    """Container and orchestration health probe verifying database connectivity."""

    def get(self, request):
        try:
            connection.ensure_connection()
            db_status = 'healthy'
            http_status = 200
        except Exception as e:
            db_status = f'unhealthy: {str(e)}'
            http_status = 503

        data = {
            'status': 'ok' if http_status == 200 else 'error',
            'database': db_status,
            'timestamp': timezone.now().isoformat(),
        }
        return JsonResponse(data, status=http_status)


health_check = HealthCheckView.as_view()
