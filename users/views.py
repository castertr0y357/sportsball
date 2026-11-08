"""
Class-Based Views for User Registration, Profile Management,
Digital Waivers (Zero-Step and Parental Consent), and Free Agent Beacon.
"""

from __future__ import annotations
from typing import Any
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import View, DetailView
from stats.models import PlayerGameStat
from leagues.models import Team, SeasonRegistration
from users.forms import CustomUserCreationForm, ProfileForm, WaiverSignatureForm
from users.models import CustomUser


class UserRegisterView(View):
    """Zero-Friction Registration: Automatically handles team/church invites and digital waiver agreement."""

    def get(self, request):
        invite_code = request.GET.get('invite')
        church_invite = request.GET.get('church_invite')
        invited_team = None
        if invite_code:
            invited_team = Team.objects.filter(invite_code=invite_code).select_related('season', 'league', 'church').first()

        if request.user.is_authenticated:
            if church_invite:
                return redirect('join_church_invite', invite_code=church_invite)
            if invited_team:
                return redirect('join_team_invite', invite_code=invite_code)
            return redirect('home')

        form = CustomUserCreationForm()
        return render(request, 'users/register.html', {
            'form': form,
            'invited_team': invited_team,
            'invite_code': invite_code,
            'church_invite': church_invite,
        })

    def post(self, request):
        invite_code = request.POST.get('invite') or request.GET.get('invite')
        church_invite = request.POST.get('church_invite') or request.GET.get('church_invite')
        invited_team = None
        if invite_code:
            invited_team = Team.objects.filter(invite_code=invite_code).select_related('season', 'league', 'church').first()

        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Zero-Step Waiver: Automatically certify waiver if checked (defaults to True)
            if form.cleaned_data.get('agree_waiver', True):
                user.sign_waiver(user.display_name)

            login(request, user, backend='users.backends.EmailOrUsernameModelBackend')

            if church_invite:
                return redirect('join_church_invite', invite_code=church_invite)

            if invited_team:
                if invited_team.players.count() < invited_team.season.max_roster_size:
                    invited_team.players.add(user)
                    user.is_free_agent = False
                    user.save(update_fields=['is_free_agent'])
                    SeasonRegistration.objects.update_or_create(
                        season=invited_team.season,
                        player=user,
                        defaults={
                            'preferred_team': invited_team,
                            'is_free_agent': False,
                            'status': 'approved',
                            'waiver_agreed': user.waiver_signed,
                        }
                    )
                    messages.success(request, f"Welcome to SportsBall, {user.first_name}! You've joined {invited_team.name} and your waiver is signed.")
                    return redirect('team_detail', team_id=invited_team.id)
                else:
                    messages.warning(request, f"Welcome {user.first_name}! {invited_team.name} has reached its maximum roster size, but your account is ready.")
                    return redirect('profile')

            messages.success(request, f"Welcome to SportsBall, {user.first_name}! Your account is ready.")
            return redirect('profile')

        return render(request, 'users/register.html', {
            'form': form,
            'invited_team': invited_team,
            'invite_code': invite_code,
            'church_invite': church_invite,
        })


class UserProfileView(LoginRequiredMixin, View):
    """Personal player profile, team memberships, captained teams, and career stat totals."""

    def get(self, request):
        user = request.user
        teams = user.teams.select_related('league', 'season', 'church').all()
        captained_teams = user.captained_teams.select_related('league', 'season', 'church').all()
        stat_totals = (
            PlayerGameStat.objects.filter(player=user)
            .values('category')
            .annotate(total=Sum('value'), games_count=Count('game', distinct=True))
            .order_by('-total')
        )
        recent_stats = (
            PlayerGameStat.objects.filter(player=user)
            .select_related('game__team1', 'game__team2', 'game__season')
            .order_by('-game__date')[:10]
        )
        return render(request, 'users/profile.html', {
            'profile_user': user,
            'teams': teams,
            'captained_teams': captained_teams,
            'stat_totals': stat_totals,
            'recent_stats': recent_stats,
            'can_see_waiver': True,
        })


class PlayerDetailView(View):
    """Public/team view of any player profile with privacy-aware waiver inspection."""

    def get(self, request, user_id: int):
        profile_user = get_object_or_404(CustomUser.objects.select_related('church'), id=user_id)
        teams = profile_user.teams.select_related('league', 'season', 'church').all()
        captained_teams = profile_user.captained_teams.select_related('league', 'season', 'church').all()
        stat_totals = (
            PlayerGameStat.objects.filter(player=profile_user)
            .values('category')
            .annotate(total=Sum('value'), games_count=Count('game', distinct=True))
            .order_by('-total')
        )
        recent_stats = (
            PlayerGameStat.objects.filter(player=profile_user)
            .select_related('game__team1', 'game__team2', 'game__season')
            .order_by('-game__date')[:10]
        )
        can_see_waiver = (
            request.user.is_authenticated and (
                request.user.id == profile_user.id or
                request.user.is_overall_commissioner or
                request.user.can_manage_church(profile_user.church) or
                request.user.captained_teams.filter(players=profile_user).exists()
            )
        )
        return render(request, 'users/profile.html', {
            'profile_user': profile_user,
            'teams': teams,
            'captained_teams': captained_teams,
            'stat_totals': stat_totals,
            'recent_stats': recent_stats,
            'can_see_waiver': can_see_waiver,
        })


class EditProfileView(LoginRequiredMixin, View):
    """Updates player contact details, jersey number, and walk-up music song settings."""

    def get(self, request):
        form = ProfileForm(instance=request.user)
        return render(request, 'users/edit_profile.html', {'form': form})

    def post(self, request):
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile and walk-up song settings have been updated.")
            return redirect('profile')
        return render(request, 'users/edit_profile.html', {'form': form})


class SignWaiverView(LoginRequiredMixin, View):
    """Digital liability waiver and Christian sportsmanship code certification."""

    def get(self, request):
        initial_name = request.user.get_full_name() or request.user.username
        form = WaiverSignatureForm(user=request.user, initial={'signature': initial_name})
        return render(request, 'users/sign_waiver.html', {'form': form})

    def post(self, request):
        form = WaiverSignatureForm(request.POST, user=request.user)
        if form.is_valid():
            request.user.sign_waiver(form.cleaned_data['signature'])
            messages.success(request, "Thank you! Your liability waiver and sportsmanship covenant have been certified.")
            return redirect('profile')
        return render(request, 'users/sign_waiver.html', {'form': form})


class SignParentalWaiverView(LoginRequiredMixin, View):
    """Parent/Guardian digital certification of liability and conduct waiver for youth participants."""

    def get(self, request, minor_id: int):
        minor = get_object_or_404(CustomUser, id=minor_id)
        if not self._can_sign(request.user, minor):
            messages.error(request, "Permission denied to sign parental waiver for this participant.")
            return redirect('profile')
        return render(request, 'users/sign_parental_waiver.html', {'minor': minor})

    def post(self, request, minor_id: int):
        minor = get_object_or_404(CustomUser, id=minor_id)
        if not self._can_sign(request.user, minor):
            messages.error(request, "Permission denied to sign parental waiver for this participant.")
            return redirect('profile')

        sig = request.POST.get('parent_signature', '').strip()
        phone = request.POST.get('parent_phone', '').strip()
        name = request.POST.get('parent_name', '').strip() or request.user.display_name
        if sig:
            minor.sign_parental_waiver(signature_name=sig, phone=phone, name=name)
            messages.success(request, f"✓ Parental consent and liability waiver recorded for {minor.display_name}!")
            return redirect('player_detail', user_id=minor.id)
        else:
            messages.error(request, "Electronic signature is required to certify parental consent.")
            return render(request, 'users/sign_parental_waiver.html', {'minor': minor})

    def _can_sign(self, user, minor):
        return (
            user.is_overall_commissioner or
            user.id == minor.parent_guardian_id or
            user.can_manage_church(minor.church)
        )


class FreeAgentListView(LoginRequiredMixin, View):
    """Directory of unassigned free agents for team coaches looking to recruit."""

    def get(self, request):
        if not request.user.can_manage_teams:
            messages.info(request, "The Free Agent directory is reserved for team coaches and league leaders looking to recruit players.")
            return redirect('home')

        free_agents = CustomUser.objects.filter(is_free_agent=True).select_related('church').order_by('username')
        return render(request, 'users/free_agents.html', {'free_agents': free_agents})


class ToggleSubAvailabilityView(LoginRequiredMixin, View):
    """1-Tap toggle broadcasting player availability for emergency substitute call-ups."""

    def post(self, request):
        return self._toggle(request)

    def get(self, request):
        return self._toggle(request)

    def _toggle(self, request):
        user = request.user
        user.is_sub_available = not user.is_sub_available
        user.save(update_fields=['is_sub_available'])
        state = "Available to Sub" if user.is_sub_available else "Not Available to Sub"
        messages.success(request, f"Updated your sub beacon: {state}!")
        return redirect(request.POST.get('next') or request.META.get('HTTP_REFERER') or 'profile')


# ============================================================================
# Callable view functions for backwards compatibility
# ============================================================================
register = UserRegisterView.as_view()
profile = UserProfileView.as_view()
player_detail = PlayerDetailView.as_view()
edit_profile = EditProfileView.as_view()
sign_waiver = SignWaiverView.as_view()
sign_parental_waiver_view = SignParentalWaiverView.as_view()
free_agent_list = FreeAgentListView.as_view()
toggle_sub_availability = ToggleSubAvailabilityView.as_view()
