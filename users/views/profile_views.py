"""
Views for Player Profiles, Edit Profile, Free Agent Beacon, and Sub Availability.
"""
from __future__ import annotations
from typing import Any
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import View, DetailView
from stats.models import PlayerGameStat
from users.forms import ProfileForm
from users.models import CustomUser


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
