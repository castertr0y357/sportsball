from __future__ import annotations
import io
import math
import os
import struct
import wave
import zipfile
from typing import Optional, Dict, Any, List

from django.core.files.base import ContentFile
from django.utils.text import slugify
from leagues.models.voice_announcer import VoicePack, VoiceClip, SoundboardEffect


def generate_synthesized_fx_wav(fx_type: str, duration_sec: float = 3.0) -> bytes:
    """
    Generates lightweight synthetic audio WAV data in memory for demo soundboard effects
    so that tests and offline local environments have instant, working audio assets.
    """
    sample_rate = 22050
    total_samples = int(sample_rate * duration_sec)
    buf = io.BytesIO()

    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()

        if fx_type == 'yakety_sax':
            # Zany fast bouncy arpeggio (C - E - G - A - C - Bb - G - F)
            scale = [261.63, 329.63, 392.00, 440.00, 523.25, 466.16, 392.00, 349.23]
            note_len = int(sample_rate * 0.12)
            for i in range(total_samples):
                note_idx = (i // note_len) % len(scale)
                f = scale[note_idx]
                t = i / sample_rate
                # Add reed harmonic richness for saxophone flavor
                val = 0.4 * math.sin(2 * math.pi * f * t) + 0.3 * math.sin(4 * math.pi * f * t) + 0.2 * math.sin(6 * math.pi * f * t)
                sample = int(max(-32767, min(32767, val * 16000)))
                frames.extend(struct.pack('<h', sample))

        elif fx_type == 'organ_charge':
            # Classic ballpark fanfare: G4 - C5 - E5 - G5 (hold) - (pause) - CHARGE!
            notes = [(392.00, 0.2), (523.25, 0.2), (659.25, 0.2), (783.99, 0.5), (0.0, 0.2), (783.99, 0.2), (1046.50, 0.6)]
            total_time = 0.0
            idx = 0
            cur_note, cur_dur = notes[0]
            for i in range(total_samples):
                t = i / sample_rate
                if t - total_time >= cur_dur and idx < len(notes) - 1:
                    total_time += cur_dur
                    idx += 1
                    cur_note, cur_dur = notes[idx]
                if cur_note > 0:
                    val = 0.5 * math.sin(2 * math.pi * cur_note * t) + 0.3 * math.sin(4 * math.pi * cur_note * t)
                else:
                    val = 0.0
                sample = int(max(-32767, min(32767, val * 16000)))
                frames.extend(struct.pack('<h', sample))

        elif fx_type == 'sad_trombone':
            # Sliding descending minor tones: D4 -> C#4 -> C4 -> B3 (wah-wah-wah-waaaah)
            slide = [293.66, 277.18, 261.63, 246.94]
            step_len = total_samples // len(slide)
            for i in range(total_samples):
                idx = min(len(slide) - 1, i // step_len)
                f = slide[idx]
                # Tremolo wobble for "wah wah"
                wobble = 1.0 + 0.2 * math.sin(2 * math.pi * 8 * (i / sample_rate))
                val = 0.5 * math.sin(2 * math.pi * f * (i / sample_rate)) * wobble
                sample = int(max(-32767, min(32767, val * 15000)))
                frames.extend(struct.pack('<h', sample))

        elif fx_type == 'foghorn':
            # Low, resonant double blast
            f1, f2 = 110.0, 116.54  # Minor second beat note for deep stadium horn
            for i in range(total_samples):
                t = i / sample_rate
                envelope = 1.0 if t < 2.5 else max(0.0, 1.0 - (t - 2.5) * 2)
                val = (0.5 * math.sin(2 * math.pi * f1 * t) + 0.5 * math.sin(2 * math.pi * f2 * t)) * envelope
                sample = int(max(-32767, min(32767, val * 20000)))
                frames.extend(struct.pack('<h', sample))

        elif fx_type == 'crickets':
            # High-pitched periodic clicks/chirps
            for i in range(total_samples):
                t = i / sample_rate
                burst = int(t * 3) % 2 == 0
                val = (0.4 * math.sin(2 * math.pi * 4800.0 * t)) if burst and ((int(t * 40) % 2) == 0) else 0.0
                sample = int(max(-32767, min(32767, val * 10000)))
                frames.extend(struct.pack('<h', sample))

        else:
            # Default cheerful notification stinger
            f = 440.0
            for i in range(total_samples):
                t = i / sample_rate
                val = 0.4 * math.sin(2 * math.pi * f * t) * (1.0 - (t / duration_sec))
                sample = int(max(-32767, min(32767, val * 14000)))
                frames.extend(struct.pack('<h', sample))

        wf.writeframes(bytes(frames))
    return buf.getvalue()


class VoiceAnnouncerService:
    """
    Core engine managing multi-sport voice packs, situational play resolution,
    fallback ladders, and soundboard audio distribution.
    """

    @classmethod
    def get_soundboard_catalog(cls) -> List[Dict[str, Any]]:
        """
        Returns all active soundboard effects grouped and serialized for the Dugout Console drawer.
        """
        cls.ensure_default_soundboard_seeded()
        effects = SoundboardEffect.objects.filter(is_active=True).order_by('category', 'display_order')
        output = []
        for fx in effects:
            output.append({
                'id': fx.id,
                'name': fx.name,
                'slug': fx.slug,
                'category': fx.category,
                'category_display': fx.get_category_display(),
                'icon': fx.icon,
                'audio_url': fx.audio_file.url if fx.audio_file else '',
                'duration': fx.audio_duration,
                'loop_mode': fx.loop_mode,
                'hotkey': fx.hotkey,
            })
        return output

    @classmethod
    def resolve_play_announcement(cls, game, event_type: str, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Resolves an audio announcement clip for a play event.
        Evaluates situational tag (bases_loaded, two_outs, etc.) and uses fallback ladder.
        """
        pack = game.get_effective_voice_pack()
        if not pack or not pack.is_active:
            return None

        ctx = context or {}
        situational_tag = 'generic'

        # Detect situational context from game state
        if game.runner_on_first and game.runner_on_second and game.runner_on_third:
            situational_tag = 'bases_loaded'
        elif game.outs == 2:
            situational_tag = 'two_outs'
        elif ctx.get('is_walk_off'):
            situational_tag = 'walk_off'
        elif ctx.get('lead_change'):
            situational_tag = 'lead_change'

        clip = pack.get_clip(event_type=event_type, situational_tag=situational_tag)
        if not clip or not clip.audio_file:
            return None

        # Increment play usage count
        clip.play_count += 1
        clip.save(update_fields=['play_count'])

        return {
            'voice_pack': pack.name,
            'event_type': event_type,
            'situational_tag': situational_tag,
            'audio_url': clip.audio_file.url,
            'transcript': clip.transcript or event_type.replace('_', ' ').title(),
            'duration': clip.audio_duration,
        }

    @classmethod
    def resolve_batter_intro(cls, game, batter_user) -> Dict[str, Any]:
        """
        Resolves PA announcer introduction for an upcoming batter.
        Priority:
        1. Player's custom recorded announcer intro clip
        2. Voice pack generic batter intro clip
        3. Text transcript fallback for browser local speech synthesis
        """
        full_name = batter_user.get_full_name() or batter_user.display_name
        number_str = f"#{batter_user.jersey_number}" if batter_user.jersey_number else ""
        transcript = f"Now batting, {number_str} {full_name}".strip()

        # 1. Custom pre-recorded player clip
        if hasattr(batter_user, 'custom_announcer_clip') and batter_user.custom_announcer_clip:
            return {
                'audio_url': batter_user.custom_announcer_clip.url,
                'transcript': transcript,
                'duration': 2.5,
                'is_custom': True,
            }

        # 2. Check active voice pack batter_intro
        pack = game.get_effective_voice_pack()
        if pack and pack.is_active:
            clip = pack.get_clip('batter_intro', 'generic')
            if clip and clip.audio_file:
                clip.play_count += 1
                clip.save(update_fields=['play_count'])
                return {
                    'audio_url': clip.audio_file.url,
                    'transcript': clip.transcript or transcript,
                    'duration': clip.audio_duration or 2.0,
                    'is_custom': False,
                }

        # 3. Graceful fallback (Text-only for browser Speech API or silent skip to walkup fanfare)
        return {
            'audio_url': None,
            'transcript': transcript,
            'duration': 0.0,
            'is_custom': False,
        }

    @classmethod
    def ensure_default_soundboard_seeded(cls):
        """
        Ensures the 6 essential soundboard effects are populated in the database with
        synthesized demo WAV assets so the feature is immediately testable and functional.
        """
        defaults = [
            ("Yakety Sax (The Pickle Button)", "yakety_sax", "chaos", "🎷", True, "P", 1, "yakety_sax", 6.0),
            ("Ballpark Organ Charge", "organ_charge", "rally", "🎺", False, "C", 2, "organ_charge", 3.0),
            ("Sad Trombone (Wah-Wah-Wah)", "sad_trombone", "chaos", "🎺", False, "S", 3, "sad_trombone", 3.5),
            ("Home Run Stadium Foghorn", "foghorn", "celebration", "🚨", False, "H", 4, "foghorn", 4.0),
            ("Crickets Chirping", "crickets", "chaos", "🦗", False, "K", 5, "crickets", 2.5),
            ("Circus Calliope (Defensive Chaos)", "circus_calliope", "chaos", "🎪", True, "", 6, "yakety_sax", 4.0),
            ("Boomshakalaka! (NBA Jam)", "boomshakalaka", "celebration", "🔥", False, "B", 7, "organ_charge", 2.0),
            ("BOOM! (Madden Fanfare)", "madden_boom", "celebration", "💥", False, "M", 8, "foghorn", 2.5),
        ]

        for name, slug, cat, icon, loop, hotkey, order, synth_type, dur in defaults:
            effect = SoundboardEffect.objects.filter(slug=slug).first()
            if not effect:
                effect = SoundboardEffect(
                    name=name,
                    slug=slug,
                    category=cat,
                    icon=icon,
                    loop_mode=loop,
                    hotkey=hotkey,
                    display_order=order,
                    audio_duration=dur,
                    is_active=True,
                )
                wav_data = generate_synthesized_fx_wav(synth_type, duration_sec=dur)
                effect.audio_file.save(f"{slug}.wav", ContentFile(wav_data), save=False)
                effect.save()

    @classmethod
    def import_voice_pack_from_zip(cls, zip_source, name: str, sport: str, slug: Optional[str] = None, author: str = '', is_default: bool = False) -> VoicePack:
        """
        Ingests a ZIP file containing structured audio clips and registers a complete VoicePack.
        Folder structure convention in zip:
          /walk/*.wav, /walk/*.mp3
          /strikeout/*.mp3
          /home_run/*.mp3
          /single/*.mp3
          /double/*.mp3
          /error/*.mp3
          /batter_intro/*.mp3
        """
        pack_slug = slug or slugify(name)
        pack, _ = VoicePack.objects.update_or_create(
            slug=pack_slug,
            defaults={
                'name': name,
                'sport': sport,
                'author': author,
                'is_active': True,
                'is_default': is_default,
            }
        )

        with zipfile.ZipFile(zip_source, 'r') as z:
            for filepath in z.namelist():
                if filepath.endswith('/') or '__MACOSX' in filepath or filepath.startswith('.'):
                    continue

                filename = os.path.basename(filepath)
                if not filename:
                    continue

                parts = filepath.strip('/').split('/')
                # If files are in a folder, use folder name as event_type
                event_type = parts[-2] if len(parts) >= 2 else os.path.splitext(filename)[0].split('_')[0]
                event_type = slugify(event_type).replace('-', '_')

                # Check situational tag if file has tag (e.g. walk_bases_loaded.mp3)
                base_name = os.path.splitext(filename)[0]
                situational_tag = 'generic'
                for tag in ['bases_loaded', 'two_outs', 'clutch', 'lead_change', 'blowout']:
                    if tag in base_name:
                        situational_tag = tag
                        break

                content = z.read(filepath)
                clip = VoiceClip(
                    voice_pack=pack,
                    event_type=event_type,
                    situational_tag=situational_tag,
                    transcript=base_name.replace('_', ' ').title(),
                    audio_duration=3.0,
                )
                clip.audio_file.save(f"{pack_slug}_{event_type}_{filename}", ContentFile(content), save=False)
                clip.save()

        return pack
