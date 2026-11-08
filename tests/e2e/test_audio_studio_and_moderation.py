import os
from django.core.files.uploadedfile import SimpleUploadedFile
from tests.e2e.base_e2e import BasePlaywrightTestCase
from users.models.walkup import AudioTrack


class AudioStudioAndModerationE2ETest(BasePlaywrightTestCase):
    """
    E2E browser tests for Walk-Up Audio Studio, Sub-Second Trimmer UI,
    League Jukebox adoption, and Coach Moderation / Veto workflows.
    """

    def setUp(self):
        super().setUp()

        # Create a sample MP3 file for Josh
        audio_file = SimpleUploadedFile("gospel_rock.mp3", b"\xFF\xFB\x90\x44" * 100, content_type="audio/mpeg")
        self.josh_track = AudioTrack.objects.create(
            user=self.player_josh,
            title="Victory Anthem - Sovereign Grace Band",
            audio_file=audio_file,
            start_seconds=13.4,
            duration_seconds=15.0,
            status="approved",
            is_public_jukebox=True,
        )
        self.player_josh.active_walkup_track = self.josh_track
        self.player_josh.save(update_fields=['active_walkup_track'])

        # Team intro track for Grace Sluggers
        team_file = SimpleUploadedFile("sluggers_intro.mp3", b"\xFF\xFB\x90\x44" * 100, content_type="audio/mpeg")
        self.sluggers_track = AudioTrack.objects.create(
            user=self.coach_grace,
            title="Sluggers Walk-On - Grace Brass",
            audio_file=team_file,
            start_seconds=0.0,
            duration_seconds=20.0,
            status="approved",
            is_public_jukebox=False,
        )
        self.team_sluggers.intro_track = self.sluggers_track
        self.team_sluggers.save(update_fields=['intro_track'])

    def test_audio_studio_navigation_and_sliders_ui(self):
        page = self.page

        # 1. Josh logs in and navigates to the Audio Studio
        self.login_as(page, self.player_josh)
        studio_url = f"{self.live_server_url}/users/profile/audio-studio/"
        page.goto(studio_url)
        page.wait_for_load_state("networkidle")

        # 2. Check tab headers and active walkup card
        self.assertIn("Ballpark Audio Studio", page.content())
        self.assertIn("Victory Anthem", page.content())
        self.assertIn("Active Game-Day Track", page.content())
        self.assertIn("13.4s", page.content())

        # 3. Open Upload & Precision Cut tab
        upload_tab_btn = page.locator("#tab-upload-btn")
        upload_tab_btn.click()
        page.wait_for_timeout(300)

        # 4. Verify precision dual sliders and nudge controls are rendered
        start_slider = page.locator("#trimStartSlider")
        end_slider = page.locator("#trimEndSlider")
        self.assertTrue(start_slider.is_visible())
        self.assertTrue(end_slider.is_visible())
        self.assertEqual(start_slider.get_attribute("step"), "0.1")
        self.assertEqual(end_slider.get_attribute("step"), "0.1")

    def test_jukebox_adoption_and_coach_veto_moderation(self):
        page = self.page

        # 1. Sarah logs in and browses the League Jukebox
        self.login_as(page, self.player_sarah)
        page.goto(f"{self.live_server_url}/users/profile/audio-studio/?tab=jukebox")
        page.wait_for_load_state("networkidle")

        self.assertIn("League Jukebox", page.content())
        self.assertIn("Victory Anthem", page.content())

        # Adopt Josh's track
        adopt_btn = page.locator(f'form[action*="/users/profile/audio-studio/{self.josh_track.id}/adopt/"] button').first
        self.assertTrue(adopt_btn.is_visible())
        adopt_btn.click()
        page.wait_for_load_state("networkidle")

        # Sarah's active walkup should now be updated with the adopted track title
        self.player_sarah.refresh_from_db()
        self.assertIsNotNone(self.player_sarah.active_walkup_track)
        self.assertEqual(self.player_sarah.active_walkup_track.title, self.josh_track.title)

        # 2. Coach Grace logs in to moderate / veto
        self.login_as(page, self.coach_grace)
        page.goto(f"{self.live_server_url}/users/profile/audio-studio/?tab=jukebox")
        page.wait_for_load_state("networkidle")

        # Verify coach sees Veto button in Jukebox
        veto_btn = page.locator('button:has-text("Veto Song")').first
        self.assertTrue(veto_btn.is_visible())
        veto_btn.click()
        page.wait_for_timeout(300)

        # Modal opens: Fill out veto reason and submit
        modal_reason_input = page.locator("#vetoReasonInput")
        self.assertTrue(modal_reason_input.is_visible())
        modal_reason_input.fill("Inappropriate secular lyrics with unedifying themes.")
        page.locator('#vetoModal button[type="submit"]').click()
        page.wait_for_load_state("networkidle")

        # 3. Track is now vetoed
        self.josh_track.refresh_from_db()
        self.assertEqual(self.josh_track.status, "vetoed")
        self.assertEqual(self.josh_track.vetoed_by, self.coach_grace)
        self.assertIn("Inappropriate secular lyrics", self.josh_track.veto_reason)

        # 4. Josh logs back in and sees the veto notice
        self.login_as(page, self.player_josh)
        page.goto(f"{self.live_server_url}/users/profile/audio-studio/")
        page.wait_for_load_state("networkidle")

        content = page.content()
        self.assertIn("Notice Regarding Walk-Up Audio", content)
        self.assertIn("Inappropriate secular lyrics", content)

        # 5. Verify Dugout Console respects veto (song is marked vetoed and URL is silenced)
        active_walkup = self.player_josh.get_active_walkup()
        self.assertTrue(active_walkup['is_vetoed'])
        self.assertEqual(active_walkup['url'], '')
        self.assertIn("Inappropriate secular lyrics", active_walkup['veto_reason'])
