import io
import zipfile
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from core.models import Church
from users.models import CustomUser
from leagues.models import League, Season, Team, Game, VoicePack, VoiceClip, SoundboardEffect
from leagues.services.voice_announcer_service import VoiceAnnouncerService, generate_synthesized_fx_wav


class VoiceAnnouncerServiceTests(TestCase):
    def setUp(self):
        self.church = Church.objects.create(name="Grace Fellowship Church", city="Greenville", state="SC")
        self.admin = CustomUser.objects.create_superuser(
            username="admin", email="admin@sportsball.local", password="password123", role="admin"
        )
        self.coach = CustomUser.objects.create_user(
            username="coach_mike", email="coach.mike@sportsball.local", password="password123",
            role="coach", church=self.church
        )
        self.batter = CustomUser.objects.create_user(
            username="batter_josh", email="batter.josh@sportsball.local", password="password123",
            first_name="Josh", last_name="Peterson", jersey_number=12, church=self.church
        )

        self.league = League.objects.create(name="Church Softball", sport="softball", admin=self.admin)
        self.season = Season.objects.create(
            league=self.league, name="2026 Season", start_date="2026-05-01", end_date="2026-09-01", current=True
        )
        self.team1 = Team.objects.create(name="Sluggers", season=self.season, league=self.league, church=self.church, captain=self.coach)
        self.team2 = Team.objects.create(name="Crusaders", season=self.season, league=self.league, church=self.church, captain=self.coach)
        self.team1.players.add(self.batter)

        self.game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date="2026-11-10 18:00:00",
            location="Field 1",
            status="in_progress",
            current_batter=self.batter,
        )

        # Create Bob Uecker test voice pack
        self.uecker_pack = VoicePack.objects.create(
            name="Bob Uecker (Test)",
            slug="uecker_test",
            sport="softball",
            is_active=True,
            is_default=True,
        )
        dummy_wav = generate_synthesized_fx_wav("organ_charge", duration_sec=1.5)

        # Add Generic Walk clip
        self.clip_walk_generic = VoiceClip.objects.create(
            voice_pack=self.uecker_pack,
            event_type="walk",
            situational_tag="generic",
            transcript="Juuuust a bit outside!",
            audio_duration=2.0,
        )
        self.clip_walk_generic.audio_file.save("walk_gen.wav", ContentFile(dummy_wav), save=True)

        # Add Bases Loaded Walk clip
        self.clip_walk_bases_loaded = VoiceClip.objects.create(
            voice_pack=self.uecker_pack,
            event_type="walk",
            situational_tag="bases_loaded",
            transcript="Ball four, and he walks in a run!",
            audio_duration=2.5,
        )
        self.clip_walk_bases_loaded.audio_file.save("walk_bl.wav", ContentFile(dummy_wav), save=True)

    def test_single_default_voice_pack_per_sport_constraint(self):
        second_pack = VoicePack.objects.create(
            name="Second Softball Pack",
            slug="softball_second",
            sport="softball",
            is_default=True,
        )
        self.uecker_pack.refresh_from_db()
        self.assertFalse(self.uecker_pack.is_default)
        self.assertTrue(second_pack.is_default)

    def test_resolve_play_announcement_situational_matching(self):
        # 1. Generic situation (no runners)
        self.game.runner_on_first = False
        self.game.runner_on_second = False
        self.game.runner_on_third = False
        self.game.save()

        announcement = VoiceAnnouncerService.resolve_play_announcement(self.game, "walk")
        self.assertIsNotNone(announcement)
        self.assertEqual(announcement['situational_tag'], "generic")
        self.assertIn("Juuuust a bit outside", announcement['transcript'])

        # 2. Bases loaded situation
        self.game.runner_on_first = True
        self.game.runner_on_second = True
        self.game.runner_on_third = True
        self.game.save()

        announcement_bl = VoiceAnnouncerService.resolve_play_announcement(self.game, "walk")
        self.assertIsNotNone(announcement_bl)
        self.assertEqual(announcement_bl['situational_tag'], "bases_loaded")
        self.assertIn("walks in a run", announcement_bl['transcript'])

    def test_resolve_play_announcement_fallback_to_generic(self):
        # When situational tag (e.g. two_outs) doesn't exist for 'walk', fall back to 'generic'
        self.game.runner_on_first = False
        self.game.runner_on_second = False
        self.game.runner_on_third = False
        self.game.outs = 2
        self.game.save()

        announcement = VoiceAnnouncerService.resolve_play_announcement(self.game, "walk")
        self.assertIsNotNone(announcement)
        # Should gracefully fallback to generic clip
        self.assertIn("Juuuust a bit outside", announcement['transcript'])

    def test_resolve_play_announcement_returns_none_when_missing(self):
        announcement = VoiceAnnouncerService.resolve_play_announcement(self.game, "bball_dunk")
        self.assertIsNone(announcement)

    def test_resolve_batter_intro_custom_and_fallback(self):
        # Fallback without custom audio
        intro = VoiceAnnouncerService.resolve_batter_intro(self.game, self.batter)
        self.assertEqual(intro['transcript'], "Now batting, #12 Josh Peterson")
        self.assertFalse(intro['is_custom'])

        # With custom recorded clip
        dummy_wav = generate_synthesized_fx_wav("organ_charge", duration_sec=1.5)
        self.batter.custom_announcer_clip.save("josh_intro.wav", ContentFile(dummy_wav), save=True)

        intro_custom = VoiceAnnouncerService.resolve_batter_intro(self.game, self.batter)
        self.assertTrue(intro_custom['is_custom'])
        self.assertIsNotNone(intro_custom['audio_url'])

    def test_soundboard_catalog_seeding_and_retrieval(self):
        catalog = VoiceAnnouncerService.get_soundboard_catalog()
        self.assertGreaterEqual(len(catalog), 6)

        slugs = [item['slug'] for item in catalog]
        self.assertIn('yakety_sax', slugs)
        self.assertIn('organ_charge', slugs)
        self.assertIn('sad_trombone', slugs)
        self.assertIn('foghorn', slugs)

        yakety = next(item for item in catalog if item['slug'] == 'yakety_sax')
        self.assertTrue(yakety['loop_mode'])
        self.assertEqual(yakety['hotkey'], 'P')

    def test_import_voice_pack_from_zip(self):
        # Construct an in-memory ZIP archive with structured folders
        zip_buf = io.BytesIO()
        dummy_wav = generate_synthesized_fx_wav("organ_charge", duration_sec=1.0)
        with zipfile.ZipFile(zip_buf, 'w') as zf:
            zf.writestr('walk/walk_01.wav', dummy_wav)
            zf.writestr('strikeout/k_01.wav', dummy_wav)
            zf.writestr('home_run/hr_bases_loaded.wav', dummy_wav)
        zip_buf.seek(0)

        pack = VoiceAnnouncerService.import_voice_pack_from_zip(
            zip_source=zip_buf,
            name="Zipped Madden Pack",
            sport="flag_football",
            author="Frank Caliendo",
        )

        self.assertEqual(pack.name, "Zipped Madden Pack")
        self.assertEqual(pack.sport, "flag_football")
        self.assertEqual(pack.clips.count(), 3)

        hr_clip = pack.clips.filter(event_type="home_run").first()
        self.assertIsNotNone(hr_clip)
        self.assertEqual(hr_clip.situational_tag, "bases_loaded")

    def test_dugout_action_returns_announcer_payload(self):
        self.client.force_login(self.admin)
        url = reverse('dugout_action', args=[self.game.id])

        # Post 'walk' action
        resp = self.client.post(url, data={'action': 'walk'}, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIn('announcement', data)
        self.assertEqual(data['announcement']['event_type'], 'walk')
        self.assertIn("Juuuust a bit outside", data['announcement']['transcript'])
        self.assertIn('audio_url', data['announcement'])

    def test_voice_pack_admin_views(self):
        self.client.force_login(self.admin)

        # 1. List view
        list_url = reverse('voice_pack_list')
        resp = self.client.get(list_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Bob Uecker (Test)")
        self.assertContains(resp, "Yakety Sax")

        # 2. Toggle default
        toggle_url = reverse('toggle_voice_pack_default', args=[self.uecker_pack.id])
        resp_toggle = self.client.post(toggle_url)
        self.assertEqual(resp_toggle.status_code, 302)
        self.uecker_pack.refresh_from_db()
        self.assertFalse(self.uecker_pack.is_default)
