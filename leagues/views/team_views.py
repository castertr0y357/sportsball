"""
Views for Team management, roster edits, invites, dues clearance, and team calendar.
"""

from __future__ import annotations
from typing import Any
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import ListView, DetailView, View
from leagues.models import Team, Season, Game, SeasonRegistration, GameLineupEntry
from leagues.forms import TeamForm
from leagues.views.mixins import TeamCoachRequiredMixin, JsonResponseMixin
from leagues.services.calendar_feed import generate_ics_feed
from users.models import CustomUser


class TeamListView(ListView):
    """Lists teams registered in a season along with current standings."""
    model = Team
    template_name = 'leagues/team_list.html'
    context_object_name = 'teams'

    def get_queryset(self):
        self.season = get_object_or_404(Season.objects.select_related('league'), id=self.kwargs['season_id'])
        return Team.objects.filter(season=self.season).select_related('church', 'captain').prefetch_related('players')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['season'] = self.season
        context['standings'] = self.season.get_standings()
        return context


class TeamCreateView(LoginRequiredMixin, View):
    """Allows church commissioners or league admins to register a team into a season."""

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not (user.is_league_admin or user.is_church_commissioner or user.role in ('coach', 'church_admin')):
            messages.error(request, "Only Church Commissioners or League Administrators can register teams in a season.")
            season_id = kwargs.get('season_id')
            return redirect('season_detail', season_id=season_id)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, season_id: int):
        from core.models import Church
        season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
        user = request.user
        target_church = self._resolve_target_church(request, user)
        form = TeamForm(user=user, target_church=target_church, initial={
            'church': target_church,
            'captain': user if user.role == 'coach' else None,
        })
        return render(request, 'leagues/create_team.html', {
            'form': form,
            'season': season,
            'target_church': target_church,
        })

    def post(self, request, season_id: int):
        season = get_object_or_404(Season.objects.select_related('league'), id=season_id)
        user = request.user
        target_church = self._resolve_target_church(request, user)
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

        return render(request, 'leagues/create_team.html', {
            'form': form,
            'season': season,
            'target_church': target_church,
        })

    def _resolve_target_church(self, request, user):
        from core.models import Church
        church_id = request.GET.get('church_id')
        if church_id:
            target = Church.objects.filter(id=church_id).first()
            if target:
                return target
        return user.managed_churches.first() or user.church


class TeamDetailView(DetailView):
    """Team roster dashboard, schedule, pending requests, and church member quick-add."""
    model = Team
    pk_url_kwarg = 'team_id'
    template_name = 'leagues/team_detail.html'
    context_object_name = 'team'

    def get_queryset(self):
        return Team.objects.select_related('league', 'season', 'church', 'captain').prefetch_related('players')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        team = self.object
        games = (
            Game.objects.filter(season=team.season).filter(team1=team) |
            Game.objects.filter(season=team.season).filter(team2=team)
        ).select_related('team1', 'team2').order_by('date')
        pending_requests = team.registration_requests.filter(status='pending').select_related('player')
        is_captain_or_admin = (
            self.request.user.is_authenticated and self.request.user.can_manage_team(team)
        )
        invite_url = team.get_invite_url(self.request)

        available_church_members = []
        if is_captain_or_admin and team.church:
            available_church_members = list(
                team.church.members.exclude(id__in=team.players.values_list('id', flat=True)).order_by('first_name', 'last_name')
            )

        context.update({
            'games': games,
            'pending_requests': pending_requests,
            'is_captain_or_admin': is_captain_or_admin,
            'invite_url': invite_url,
            'available_church_members': available_church_members,
        })
        return context


class ManageRosterPlayerView(TeamCoachRequiredMixin, View):
    """Updates roster positions, jersey numbers, captain designations, or quick-adds church members."""

    def post(self, request, team_id: int):
        team = self.get_team()
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


class JoinTeamView(LoginRequiredMixin, View):
    """Direct join attempt informational redirect."""

    def get(self, request, team_id: int):
        team = get_object_or_404(Team.objects.select_related('season'), id=team_id)
        messages.info(request, "Joining a team roster requires an invite link from the Team Captain or an assignment by your Church Commissioner.")
        return redirect('team_detail', team_id=team.id)


class JoinTeamByInviteView(View):
    """Onboarding view for players clicking a secret team invite link."""

    def get(self, request, invite_code: str):
        team = get_object_or_404(
            Team.objects.select_related('league', 'season', 'church', 'captain').prefetch_related('players'),
            invite_code=invite_code
        )
        if not request.user.is_authenticated:
            return redirect(f"{reverse('register')}?invite={invite_code}")

        if request.user in team.players.all():
            messages.info(request, f"You are already on the roster for {team.name}!")
            return redirect('team_detail', team_id=team.id)

        return render(request, 'leagues/join_team_confirm.html', {'team': team})

    def post(self, request, invite_code: str):
        team = get_object_or_404(
            Team.objects.select_related('league', 'season', 'church', 'captain').prefetch_related('players'),
            invite_code=invite_code
        )
        if not request.user.is_authenticated:
            return redirect(f"{reverse('register')}?invite={invite_code}")

        if request.user in team.players.all():
            messages.info(request, f"You are already on the roster for {team.name}!")
            return redirect('team_detail', team_id=team.id)

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


class ToggleTeamDuesView(LoginRequiredMixin, View):
    """1-Tap Season Dues clearance toggle for League Commissioners."""

    def post(self, request, team_id: int):
        return self._toggle_dues(request, team_id)

    def get(self, request, team_id: int):
        return self._toggle_dues(request, team_id)

    def _toggle_dues(self, request, team_id: int):
        team = get_object_or_404(Team.objects.select_related('league', 'season'), id=team_id)
        if not request.user.can_manage_league(team.league):
            messages.error(request, "Only League Commissioners can update team fee dues.")
            return redirect('season_detail', season_id=team.season_id)

        team.dues_paid = not team.dues_paid
        team.save(update_fields=['dues_paid'])

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'ok', 'dues_paid': team.dues_paid, 'team_name': team.name})

        status_str = f"Paid (${team.season.registration_fee})" if team.dues_paid else "Unpaid"
        messages.success(request, f"Updated dues for '{team.name}': {status_str}")
        return redirect('season_detail', season_id=team.season_id)


class TeamCalendarIcsView(View):
    """Subscribable iCalendar feed (.ics) for a specific team's match schedule."""

    def get(self, request, team_id: int):
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


class TeamSafetyRosterView(LoginRequiredMixin, View):
    """
    Printable 1-click Safety & Emergency Contact Roster for coaches, referees, and commissioners.
    Displays emergency contact names, emergency contact phones, and waiver status.
    """

    def get(self, request, team_id: int):
        team = get_object_or_404(
            Team.objects.select_related('league', 'season', 'church', 'captain'),
            id=team_id
        )
        is_captain = team.captain_id == request.user.id
        is_commish = (
            request.user.is_overall_commissioner
            or request.user.can_manage_league(team.league)
            or (team.church and request.user.can_manage_church(team.church))
        )
        is_official = getattr(request.user, 'role', '') == 'referee' or request.user.is_staff

        if not (is_captain or is_commish or is_official):
            messages.error(request, "Permission denied: Only team captains, league commissioners, or officials may access emergency rosters.")
            return redirect('team_detail', team_id=team.id)

        players = list(team.players.all().order_by('jersey_number', 'last_name', 'first_name'))

        return render(request, 'leagues/team_safety_roster.html', {
            'team': team,
            'players': players,
            'printed_at': timezone.now(),
        })


team_safety_roster = TeamSafetyRosterView.as_view()
