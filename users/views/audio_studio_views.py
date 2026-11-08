"""
Views for Precision Walk-Up Audio Studio, Dual-Slider Trimming,
Team Intro Anthems for All Sports, Official Veto Moderation, and League Jukebox.
"""
from __future__ import annotations
from typing import Any
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import View
from leagues.models import Team
from users.models import AudioTrack, CustomUser


class AudioStudioView(LoginRequiredMixin, View):
    """Interactive Walk-Up & Team Intro Audio Studio with 4 tabs."""

    def get(self, request):
        user = request.user
        my_tracks = AudioTrack.objects.filter(user=user).select_related('replacement_track').order_by('-created_at')
        active_walkup = user.active_walkup_track

        # Managed teams for team intro anthems
        managed_teams = Team.objects.filter(
            Q(captain=user) |
            (Q(season__league__admin=user) if hasattr(user, 'is_league_admin') and user.is_league_admin else Q(pk__in=[]))
        ).select_related('league', 'season', 'church', 'intro_track').distinct()
        if user.is_overall_commissioner:
            managed_teams = Team.objects.select_related('league', 'season', 'church', 'intro_track').all()[:25]

        # League Jukebox: public, approved tracks
        jukebox_tracks = AudioTrack.objects.filter(
            is_public_jukebox=True,
            status='approved'
        ).select_related('user', 'team').order_by('-created_at')[:50]

        # Veto notifications for the current user
        vetoed_tracks = [t for t in my_tracks if t.is_vetoed]

        # Moderation permissions: Coach, Referee, Church Commissioner, League Admin, Overall Admin
        can_moderate = (
            user.is_overall_commissioner
            or getattr(user, 'is_league_admin', False)
            or getattr(user, 'is_referee', False)
            or getattr(user, 'is_church_admin', False)
            or user.role in ['coach', 'church_admin', 'referee', 'league_admin', 'admin']
            or user.captained_teams.exists()
        )

        all_approved_tracks = AudioTrack.objects.filter(status='approved').order_by('title')[:100]

        return render(request, 'users/audio_studio.html', {
            'my_tracks': my_tracks,
            'active_walkup': active_walkup,
            'managed_teams': managed_teams,
            'jukebox_tracks': jukebox_tracks,
            'vetoed_tracks': vetoed_tracks,
            'can_moderate': can_moderate,
            'all_approved_tracks': all_approved_tracks,
            'initial_tab': request.GET.get('tab', 'my_clips'),
            'selected_team_id': request.GET.get('team_id', ''),
        })


class AudioUploadTrimView(LoginRequiredMixin, View):
    """Uploads and saves a precision audio clip with sub-second offsets (e.g. 13.4s)."""

    @transaction.atomic
    def post(self, request):
        title = request.POST.get('title', '').strip() or "Untitled Walk-Up Track"
        audio_file = request.FILES.get('audio_file')
        track_type = request.POST.get('track_type', 'player_walkup')
        team_id = request.POST.get('team_id')

        try:
            start_seconds = round(float(request.POST.get('start_seconds', 0.0)), 1)
        except (ValueError, TypeError):
            start_seconds = 0.0

        try:
            duration_seconds = round(float(request.POST.get('duration_seconds', 12.0)), 1)
        except (ValueError, TypeError):
            duration_seconds = 12.0

        duration_seconds = max(1.0, min(duration_seconds, 25.0))
        is_public = request.POST.get('is_public_jukebox') == 'on'

        # Check existing file or source track
        source_track_id = request.POST.get('source_track_id')
        if not audio_file and source_track_id:
            source = get_object_or_404(AudioTrack, id=source_track_id)
            audio_file = source.audio_file

        if not audio_file:
            messages.error(request, "Audio file is required to save a walk-up or intro anthem.")
            return redirect('audio_studio')

        team = None
        if track_type == 'team_intro' and team_id:
            team = get_object_or_404(Team, id=team_id)
            if not (request.user.can_manage_league(team.league) or team.captain_id == request.user.id or request.user.is_overall_commissioner):
                messages.error(request, "Permission denied to set intro anthem for this team.")
                return redirect('audio_studio')

        track = AudioTrack.objects.create(
            track_type=track_type,
            title=title,
            audio_file=audio_file,
            start_seconds=start_seconds,
            duration_seconds=duration_seconds,
            user=request.user if track_type == 'player_walkup' else None,
            team=team,
            status='approved',
            is_active=True,
            is_public_jukebox=is_public,
        )

        if track_type == 'player_walkup':
            request.user.active_walkup_track = track
            request.user.walkup_song_title = title
            request.user.walkup_song_file = track.audio_file
            request.user.walkup_start_seconds = int(start_seconds)
            request.user.walkup_duration_seconds = int(duration_seconds)
            request.user.save(update_fields=[
                'active_walkup_track', 'walkup_song_title', 'walkup_song_file',
                'walkup_start_seconds', 'walkup_duration_seconds'
            ])
            messages.success(request, f"✓ Saved & activated walk-up cut: '{title}' ({duration_seconds}s)!")
            return redirect('audio_studio')
        else:
            team.intro_track = track
            team.save(update_fields=['intro_track'])
            messages.success(request, f"✓ Saved & activated official Team Intro Anthem for {team.name} ({duration_seconds}s)!")
            return redirect(f"/profile/audio-studio/?tab=team_anthems&team_id={team.id}")


class AudioSetActiveView(LoginRequiredMixin, View):
    """1-Tap activation of a saved walk-up cut or team intro."""

    def post(self, request, track_id: int):
        track = get_object_or_404(AudioTrack, id=track_id)
        if track.is_vetoed:
            messages.error(request, f"Cannot activate vetoed track: {track.veto_reason or 'Marked inappropriate'}")
            return redirect('audio_studio')

        target_team_id = request.POST.get('team_id')
        if track.track_type == 'team_intro' or target_team_id:
            team = get_object_or_404(Team, id=target_team_id or track.team_id)
            if not (request.user.can_manage_league(team.league) or team.captain_id == request.user.id or request.user.is_overall_commissioner):
                messages.error(request, "Permission denied to update anthem for this team.")
                return redirect('audio_studio')
            team.intro_track = track
            team.save(update_fields=['intro_track'])
            messages.success(request, f"✓ Set active Team Intro Anthem for {team.name}: '{track.title}'")
            return redirect(f"/profile/audio-studio/?tab=team_anthems&team_id={team.id}")
        else:
            if track.user_id != request.user.id and not request.user.is_overall_commissioner:
                messages.error(request, "You can only activate your own walk-up tracks.")
                return redirect('audio_studio')
            request.user.active_walkup_track = track
            request.user.walkup_song_title = track.title
            request.user.walkup_song_file = track.audio_file
            request.user.walkup_start_seconds = int(track.start_seconds)
            request.user.walkup_duration_seconds = int(track.duration_seconds)
            request.user.save(update_fields=[
                'active_walkup_track', 'walkup_song_title', 'walkup_song_file',
                'walkup_start_seconds', 'walkup_duration_seconds'
            ])
            messages.success(request, f"✓ Activated walk-up song: '{track.title}' ({track.duration_seconds:.1f}s)!")
            return redirect('audio_studio')


class AudioAdoptJukeboxView(LoginRequiredMixin, View):
    """1-Click adoption of an existing pre-cleared track from the League Jukebox."""

    @transaction.atomic
    def post(self, request, track_id: int):
        source = get_object_or_404(AudioTrack, id=track_id, is_public_jukebox=True, status='approved')
        as_team_id = request.POST.get('team_id')

        if as_team_id:
            team = get_object_or_404(Team, id=as_team_id)
            if not (request.user.can_manage_league(team.league) or team.captain_id == request.user.id or request.user.is_overall_commissioner):
                messages.error(request, "Permission denied to set intro anthem for this team.")
                return redirect('audio_studio')
            team.intro_track = source
            team.save(update_fields=['intro_track'])
            messages.success(request, f"✓ Adopted '{source.title}' as official Team Intro Anthem for {team.name}!")
            return redirect(f"/profile/audio-studio/?tab=team_anthems&team_id={team.id}")
        else:
            # Clone reference for player
            clone = AudioTrack.objects.create(
                track_type='player_walkup',
                title=source.title,
                audio_file=source.audio_file,
                start_seconds=source.start_seconds,
                duration_seconds=source.duration_seconds,
                user=request.user,
                status='approved',
                is_active=True,
                is_public_jukebox=False,
            )
            request.user.active_walkup_track = clone
            request.user.walkup_song_title = clone.title
            request.user.walkup_song_file = clone.audio_file
            request.user.walkup_start_seconds = int(clone.start_seconds)
            request.user.walkup_duration_seconds = int(clone.duration_seconds)
            request.user.save(update_fields=[
                'active_walkup_track', 'walkup_song_title', 'walkup_song_file',
                'walkup_start_seconds', 'walkup_duration_seconds'
            ])
            messages.success(request, f"⚡ Successfully adopted '{source.title}' as your active walk-up song!")
            return redirect('audio_studio')


class AudioVetoView(LoginRequiredMixin, View):
    """Official veto and replacement moderation by coaches, referees, and commissioners."""

    @transaction.atomic
    def post(self, request, track_id: int):
        track = get_object_or_404(AudioTrack.objects.select_related('user', 'team'), id=track_id)
        reason = request.POST.get('veto_reason', '').strip() or "Deemed unedifying or inappropriate for church league."
        replacement_id = request.POST.get('replacement_track_id')

        # Check authorization
        can_veto = (
            request.user.is_overall_commissioner
            or (track.user and request.user.captained_teams.filter(players=track.user).exists())
            or (track.team and (track.team.captain_id == request.user.id or request.user.can_manage_league(track.team.league)))
            or getattr(request.user, 'is_referee', False)
            or getattr(request.user, 'is_league_admin', False)
            or getattr(request.user, 'is_church_admin', False)
        )

        if not can_veto:
            messages.error(request, "You do not have permission to moderate or veto this audio track.")
            return redirect('audio_studio')

        replacement = None
        if replacement_id:
            replacement = AudioTrack.objects.filter(id=replacement_id, status='approved').first()

        track.status = 'vetoed'
        track.vetoed_by = request.user
        track.vetoed_at = timezone.now()
        track.veto_reason = reason
        track.replacement_track = replacement
        track.is_public_jukebox = False
        track.save(update_fields=[
            'status', 'vetoed_by', 'vetoed_at', 'veto_reason', 'replacement_track', 'is_public_jukebox'
        ])

        msg = f"🚫 Track '{track.title}' has been vetoed. Reason: {reason}"
        if replacement:
            msg += f" (Assigned replacement: '{replacement.title}')"
        messages.warning(request, msg)
        return redirect('audio_studio')


class AudioDeleteView(LoginRequiredMixin, View):
    """Deletes an audio track owned by user."""

    def post(self, request, track_id: int):
        track = get_object_or_404(AudioTrack, id=track_id)
        is_owner = track.user_id == request.user.id
        is_team_coach = track.team and track.team.captain_id == request.user.id
        is_admin = request.user.is_overall_commissioner

        if not (is_owner or is_team_coach or is_admin):
            messages.error(request, "Permission denied to delete this track.")
            return redirect('audio_studio')

        title = track.title
        track.delete()
        messages.success(request, f"Deleted audio track: '{title}'.")
        return redirect('audio_studio')
