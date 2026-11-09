from tests.e2e.base_e2e import BasePlaywrightTestCase
from leagues.models.voice_announcer import VoicePack, VoiceClip, SoundboardEffect
from leagues.services.voice_announcer_service import VoiceAnnouncerService, generate_synthesized_fx_wav
from django.core.files.base import ContentFile


class SoundboardAndAnnouncerE2ETest(BasePlaywrightTestCase):
    """
    E2E browser tests for Press Box Soundboard Drawer, Yakety Sax loop trigger,
    emergency killswitch, and Dugout Console audio announcer integration.
    """

    def setUp(self):
        super().setUp()
        VoiceAnnouncerService.ensure_default_soundboard_seeded()

        # Seed Bob Uecker test pack
        self.uecker_pack, _ = VoicePack.objects.get_or_create(
            slug="uecker_e2e",
            defaults={
                'name': "Bob Uecker (E2E)",
                'sport': "softball",
                'is_active': True,
                'is_default': True,
            }
        )
        dummy_wav = generate_synthesized_fx_wav("organ_charge", duration_sec=1.5)
        clip, _ = VoiceClip.objects.get_or_create(
            voice_pack=self.uecker_pack,
            event_type="walk",
            situational_tag="generic",
            defaults={
                'transcript': "Juuuust a bit outside!",
                'audio_duration': 2.0,
            }
        )
        if not clip.audio_file:
            clip.audio_file.save("uecker_walk.wav", ContentFile(dummy_wav), save=True)

    def test_press_box_soundboard_drawer_toggle_and_triggers(self):
        page = self.page

        # 1. Coach logs in and accesses the live Dugout Console
        self.login_as(page, self.coach_grace)
        dugout_url = f"{self.live_server_url}/leagues/games/{self.game.id}/console/"
        page.goto(dugout_url)
        page.wait_for_load_state("networkidle")

        # 2. Verify Soundboard FX toggle button exists in header
        sb_toggle = page.locator("#btn-soundboard-toggle")
        self.assertTrue(sb_toggle.is_visible())
        self.assertIn("Soundboard FX", sb_toggle.inner_text())

        # 3. Drawer should be initially hidden
        drawer = page.locator("#soundboardDrawer")
        self.assertFalse(drawer.is_visible())

        # 4. Click Soundboard FX button -> drawer opens
        sb_toggle.click()
        page.wait_for_timeout(300)
        self.assertTrue(drawer.is_visible())

        # 5. Verify the key soundboard buttons exist
        yakety_btn = page.locator("#btn-sb-yakety_sax")
        organ_btn = page.locator("#btn-sb-organ_charge")
        sad_btn = page.locator("#btn-sb-sad_trombone")

        self.assertTrue(yakety_btn.is_visible())
        self.assertIn("Yakety Sax", yakety_btn.inner_text())
        self.assertTrue(organ_btn.is_visible())
        self.assertTrue(sad_btn.is_visible())

        # 6. Click Yakety Sax (The Pickle Button) -> verify active looping style
        yakety_btn.click()
        page.wait_for_timeout(200)
        self.assertIn("active-looping", yakety_btn.get_attribute("class"))

        # 7. Click Emergency Killswitch -> stops all audio and removes loop state
        stop_btn = page.locator("button:has-text('STOP ALL AUDIO')")
        self.assertTrue(stop_btn.is_visible())
        stop_btn.click()
        page.wait_for_timeout(200)
        self.assertNotIn("active-looping", yakety_btn.get_attribute("class"))

        # 8. Test Comedy Commentary toggle checkbox
        chk_commentary = page.locator("#chk-commentary-enabled")
        self.assertTrue(chk_commentary.is_visible())
        self.assertFalse(chk_commentary.is_checked())
        chk_commentary.check()
        self.assertTrue(chk_commentary.is_checked())

        # 9. Close drawer
        close_btn = drawer.locator("button:has-text('Close Drawer')")
        close_btn.click()
        page.wait_for_timeout(300)
        self.assertFalse(drawer.is_visible())
