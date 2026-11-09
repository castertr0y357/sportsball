from __future__ import annotations
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import View

from leagues.models.voice_announcer import VoicePack, VoiceClip, SoundboardEffect
from leagues.services.voice_announcer_service import VoiceAnnouncerService


class SuperuserOrAdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_superuser or user.role in ('admin', 'league_admin', 'committee'))


class VoicePackListView(SuperuserOrAdminRequiredMixin, View):
    """Admin dashboard to view voice packs, soundboard effects, audition clips, and upload ZIP packs."""

    def get(self, request):
        VoiceAnnouncerService.ensure_default_soundboard_seeded()
        voice_packs = VoicePack.objects.prefetch_related('clips').all().order_by('sport', 'name')
        soundboard_effects = SoundboardEffect.objects.all().order_by('display_order', 'name')

        return render(request, 'leagues/voice_packs_admin.html', {
            'voice_packs': voice_packs,
            'soundboard_effects': soundboard_effects,
        })


class VoicePackUploadZipView(SuperuserOrAdminRequiredMixin, View):
    """Handles bulk ZIP archive upload for registering complete multi-clip Voice Packs."""

    def post(self, request):
        name = request.POST.get('name', '').strip()
        sport = request.POST.get('sport', 'softball')
        author = request.POST.get('author', '').strip()
        is_default = bool(request.POST.get('is_default'))
        zip_file = request.FILES.get('zip_file')

        if not name or not zip_file:
            messages.error(request, "Both a Voice Pack Name and a ZIP file are required.")
            return redirect('voice_pack_list')

        try:
            pack = VoiceAnnouncerService.import_voice_pack_from_zip(
                zip_source=zip_file,
                name=name,
                sport=sport,
                author=author,
                is_default=is_default,
            )
            clip_count = pack.clips.count()
            messages.success(request, f"Successfully created Voice Pack '{pack.name}' with {clip_count} audio clips!")
        except Exception as e:
            messages.error(request, f"Failed to ingest ZIP archive: {e}")

        return redirect('voice_pack_list')


class ToggleVoicePackDefaultView(SuperuserOrAdminRequiredMixin, View):
    """Sets a Voice Pack as the default announcer for its sport."""

    def post(self, request, pack_id: int):
        pack = get_object_or_404(VoicePack, id=pack_id)
        pack.is_default = not pack.is_default
        pack.save()
        status_text = "now default" if pack.is_default else "no longer default"
        messages.success(request, f"Voice Pack '{pack.name}' is {status_text} for {pack.get_sport_display() if hasattr(pack, 'get_sport_display') else pack.sport}.")
        return redirect('voice_pack_list')
