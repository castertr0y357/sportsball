"""
Views for User Registration with Zero-Step Waivers and Parental Consent.
"""
from __future__ import annotations
from typing import Any
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import View
from leagues.models import Team, SeasonRegistration
from users.forms import CustomUserCreationForm, WaiverSignatureForm
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
