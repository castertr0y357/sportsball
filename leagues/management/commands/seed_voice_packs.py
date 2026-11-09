from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from leagues.models.voice_announcer import VoicePack, VoiceClip
from leagues.services.voice_announcer_service import VoiceAnnouncerService, generate_synthesized_fx_wav


class Command(BaseCommand):
    help = "Seeds default sports announcer Voice Packs (Bob Uecker, NBA Jam, John Madden) and Soundboard FX"

    def handle(self, *args, **options):
        self.stdout.write("Seeding Press Box Soundboard effects...")
        VoiceAnnouncerService.ensure_default_soundboard_seeded()

        self.stdout.write("Seeding Signature Multi-Sport Voice Packs...")

        packs_data = [
            # 1. SOFTBALL: Bob Uecker
            {
                'name': "Bob Uecker (Major League Edition)",
                'slug': "uecker",
                'sport': "softball",
                'author': "Major League Radio Tribute",
                'description': "Classic deadpan, self-deprecating ballpark humor. Famous for 'Juuuust a bit outside!'.",
                'is_default': True,
                'clips': [
                    ("walk", "generic", "Juuuust a bit outside, he tried for the corner and missed!"),
                    ("walk", "bases_loaded", "Ball twelve, and he walks in a run on twelve consecutive pitches!"),
                    ("strikeout", "generic", "Got 'im looking! Strike three called on the corner."),
                    ("strikeout", "two_outs", "Swung on and missed, and that will retire the side!"),
                    ("home_run", "generic", "Get up, get out of here, gone! A towering blast into the trees!"),
                    ("single", "generic", "Drills one into the outfield for a clean base hit."),
                    ("double", "generic", "Ripped into the gap! He'll pull into second with a stand-up double."),
                    ("triple", "generic", "Off the fence! He is chugging for third and makes it with a triple!"),
                    ("error", "generic", "Oh boy, a little miscue in the field and everybody is safe."),
                    ("batter_intro", "generic", "Stepping in now, let's see what he can do here."),
                ]
            },
            # 2. BASKETBALL: NBA Jam Tim Kitzrow
            {
                'name': "NBA Jam Announcer (Tim Kitzrow)",
                'slug': "nba_jam",
                'sport': "basketball",
                'author': "Midway Arcade Tribute",
                'description': "High-octane arcade commentary: 'Boomshakalaka!', 'He's on fire!', 'From downtown!'.",
                'is_default': True,
                'clips': [
                    ("bball_dunk", "generic", "Boomshakalaka!"),
                    ("bball_he_is_on_fire", "generic", "He's heating up... HE'S ON FIRE!"),
                    ("bball_three_pointer", "generic", "From downtown! YES!"),
                    ("bball_block", "generic", "Rejected! Get that outta here!"),
                    ("bball_steal", "generic", "Is it the shoes?! Steal!"),
                    ("two_pointer", "generic", "Count it! And the foul!"),
                    ("batter_intro", "generic", "Checking in, ready to rock the rim!"),
                ]
            },
            # 3. FLAG FOOTBALL: John Madden / Frank Caliendo
            {
                'name': "John Madden (Boom Edition)",
                'slug': "madden",
                'sport': "flag_football",
                'author': "All-Madden Tribute",
                'description': "Energetic telestrator wisdom: 'BOOM!', 'Now here's a guy...', 'Turducken time!'.",
                'is_default': True,
                'clips': [
                    ("football_touchdown", "generic", "BOOM! Touchdown! You see him hit that pylon?!"),
                    ("football_first_down", "generic", "Now here's a guy who when he runs, he moves forward for a first down!"),
                    ("football_sack", "generic", "BOOM! Right in the grass! Tough acting Tenactin!"),
                    ("football_interception", "generic", "Picked off! What was he thinking?! Turducken time!"),
                    ("two_pointer", "generic", "Two-point conversion is GOOD! Bam!"),
                    ("batter_intro", "generic", "Lining up under center, ready to make a play!"),
                ]
            },
        ]

        # Generate a fast generic announcer tone
        cached_clip_wav = generate_synthesized_fx_wav("organ_charge", duration_sec=2.5)

        for p_data in packs_data:
            pack, _ = VoicePack.objects.update_or_create(
                slug=p_data['slug'],
                defaults={
                    'name': p_data['name'],
                    'sport': p_data['sport'],
                    'author': p_data['author'],
                    'description': p_data['description'],
                    'is_default': p_data['is_default'],
                    'is_active': True,
                }
            )

            for event_type, tag, transcript in p_data['clips']:
                clip = VoiceClip.objects.filter(voice_pack=pack, event_type=event_type, situational_tag=tag).first()
                if not clip:
                    clip = VoiceClip(
                        voice_pack=pack,
                        event_type=event_type,
                        situational_tag=tag,
                        transcript=transcript,
                        audio_duration=2.5,
                    )
                    clip.audio_file.save(f"{pack.slug}_{event_type}_{tag}.wav", ContentFile(cached_clip_wav), save=False)
                    clip.save()
                else:
                    clip.transcript = transcript
                    clip.save(update_fields=['transcript'])

        self.stdout.write(self.style.SUCCESS(
            "Successfully seeded Press Box Soundboard & Signature Voice Packs!\n"
            " • 8 Soundboard Effects (Yakety Sax, Organ Charge, Sad Trombone, Foghorn, etc.)\n"
            " • 3 Signature Voice Packs:\n"
            "   - Softball: Bob Uecker (10 clips)\n"
            "   - Basketball: NBA Jam (7 clips)\n"
            "   - Flag Football: John Madden (6 clips)"
        ))
