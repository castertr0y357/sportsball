"""
Unit tests for Precision Walk-Up Audio Studio, Sub-Second Dual Sliders (13.4s),
Team Intro Anthems for All Sports, Coach & Official Veto Moderation, and Jukebox.
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Church
from leagues.models import League, Season, Team
from users.models import AudioTrack, CustomUser


class TestAudioStudioSuite(TestCase):
    def setUp(self):
        self.church = Church.objects.create(name="Hope Fellowship Church", city="Spartanburg", state="SC")
        self.admin = CustomUser.objects.create_user(
            username="commish_admin",
            password="pass123",
            role="admin",
            church=self.church
        )
        self.coach = CustomUser.objects.create_user(
            username="coach_tim",
            password="pass123",
            role="coach",
            church=self.church
        )
        self.player1 = CustomUser.objects.create_user(
            username="player_sam",
            password="pass123",
            role="player",
            church=self.church
        )
        self.player2 = CustomUser.objects.create_user(
            username="player_dave",
            password="pass123",
            role="player",
            church=self.church
        )

        self.league = League.objects.create(name="Community Church League", sport="softball", admin=self.admin)
        self.season = Season.objects.create(
            league=self.league,
            name="Spring 2026",
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timezone.timedelta(days=90),
            current=True
        )
        self.team = Team.objects.create(
            name="Grace Warriors",
            league=self.league,
            season=self.season,
            church=self.church,
            captain=self.coach
        )
        self.team.players.add(self.player1)

        self.sample_audio = SimpleUploadedFile("song.mp3", b"dummy audio content", content_type="audio/mpeg")

    def test_audio_track_creation_and_precision_subsecond_timing(self):
        """Audio track stores exact floating-point offsets (e.g. 13.4s) and updates active walkup."""
        track = AudioTrack.objects.create(
            user=self.player1,
            title="Survivor - Eye of the Tiger",
            audio_file=self.sample_audio,
            start_seconds=45.2,
            duration_seconds=13.4,
            status='approved',
            is_active=True,
            is_public_jukebox=True
        )
        self.player1.active_walkup_track = track
        self.player1.save()

        # Check sub-second precision end point
        self.assertEqual(track.end_seconds, 58.6)

        # Check player.get_active_walkup()
        walkup = self.player1.get_active_walkup()
        self.assertEqual(walkup['title'], "Survivor - Eye of the Tiger")
        self.assertEqual(walkup['start'], 45.2)
        self.assertEqual(walkup['duration'], 13.4)
        self.assertFalse(walkup['is_vetoed'])
        self.assertTrue(walkup['url'].endswith('.mp3'))
        self.assertIn('song', walkup['url'])

    def test_team_intro_anthem_assignment(self):
        """Team intro anthems across all sports can be clipped and assigned to teams."""
        anthem = AudioTrack.objects.create(
            team=self.team,
            track_type='team_intro',
            title="Warriors Stadium Anthem",
            audio_file=self.sample_audio,
            start_seconds=10.0,
            duration_seconds=18.5,
            status='approved'
        )
        self.team.intro_track = anthem
        self.team.save()

        intro = self.team.get_active_intro()
        self.assertEqual(intro['title'], "Warriors Stadium Anthem")
        self.assertEqual(intro['start'], 10.0)
        self.assertEqual(intro['duration'], 18.5)
        self.assertFalse(intro['is_vetoed'])

    def test_coach_veto_permission_and_silencing(self):
        """Coaches can veto unedifying songs for players on their roster, immediately silencing them."""
        track = AudioTrack.objects.create(
            user=self.player1,
            title="Questionable Song",
            audio_file=self.sample_audio,
            start_seconds=0.0,
            duration_seconds=12.0,
            status='approved',
            is_public_jukebox=True
        )
        self.player1.active_walkup_track = track
        self.player1.save()

        # Coach submits veto
        self.client.force_login(self.coach)
        url = reverse('audio_veto', kwargs={'track_id': track.id})
        resp = self.client.post(url, {
            'veto_reason': "Inappropriate and explicit lyrics."
        })
        self.assertEqual(resp.status_code, 302)

        track.refresh_from_db()
        self.assertTrue(track.is_vetoed)
        self.assertEqual(track.vetoed_by, self.coach)
        self.assertEqual(track.veto_reason, "Inappropriate and explicit lyrics.")
        self.assertFalse(track.is_public_jukebox)

        # Silenced during match play
        walkup = self.player1.get_active_walkup()
        self.assertTrue(walkup['is_vetoed'])
        self.assertEqual(walkup['url'], "")  # Silenced
        self.assertEqual(walkup['veto_reason'], "Inappropriate and explicit lyrics.")

    def test_coach_veto_with_replacement_track(self):
        """Coach can veto a track and assign an approved replacement track."""
        bad_track = AudioTrack.objects.create(
            user=self.player1,
            title="Bad Lyrics Song",
            audio_file=self.sample_audio,
            start_seconds=0.0,
            duration_seconds=12.0,
            status='approved'
        )
        self.player1.active_walkup_track = bad_track
        self.player1.save()

        good_replacement = AudioTrack.objects.create(
            title="Approved Christian Rock Anthem",
            audio_file=self.sample_audio,
            start_seconds=15.0,
            duration_seconds=14.0,
            status='approved'
        )

        self.client.force_login(self.coach)
        url = reverse('audio_veto', kwargs={'track_id': bad_track.id})
        resp = self.client.post(url, {
            'veto_reason': "Not suitable for church ballpark.",
            'replacement_track_id': good_replacement.id
        })
        self.assertEqual(resp.status_code, 302)

        bad_track.refresh_from_db()
        self.assertTrue(bad_track.is_vetoed)
        self.assertEqual(bad_track.replacement_track, good_replacement)

        # Player walkup effectively returns the replacement track
        walkup = self.player1.get_active_walkup()
        self.assertFalse(walkup['is_vetoed'])
        self.assertEqual(walkup['title'], "Approved Christian Rock Anthem")
        self.assertEqual(walkup['start'], 15.0)
        self.assertEqual(walkup['duration'], 14.0)

    def test_unauthorized_player_cannot_veto(self):
        """Random players cannot veto songs of other players."""
        track = AudioTrack.objects.create(
            user=self.player1,
            title="Player 1 Track",
            audio_file=self.sample_audio,
            start_seconds=0.0,
            duration_seconds=12.0,
            status='approved'
        )
        self.client.force_login(self.player2)  # Unrelated player
        url = reverse('audio_veto', kwargs={'track_id': track.id})
        resp = self.client.post(url, {'veto_reason': "I don't like it."})
        self.assertEqual(resp.status_code, 302)

        track.refresh_from_db()
        self.assertFalse(track.is_vetoed)
        self.assertEqual(track.status, 'approved')

    def test_jukebox_adoption(self):
        """Players can adopt approved tracks from the Jukebox with 1 click without uploading files."""
        public_track = AudioTrack.objects.create(
            title="TobyMac - Feel It",
            audio_file=self.sample_audio,
            start_seconds=22.4,
            duration_seconds=13.4,
            status='approved',
            is_public_jukebox=True
        )

        self.client.force_login(self.player2)
        url = reverse('audio_adopt_jukebox', kwargs={'track_id': public_track.id})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)

        self.player2.refresh_from_db()
        self.assertIsNotNone(self.player2.active_walkup_track)
        self.assertEqual(self.player2.active_walkup_track.title, "TobyMac - Feel It")
        self.assertEqual(self.player2.active_walkup_track.duration_seconds, 13.4)

    def test_audio_studio_view_renders(self):
        """Audio Studio dashboard renders 200 OK with tabs and user context."""
        self.client.force_login(self.player1)
        resp = self.client.get(reverse('audio_studio'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ballpark Audio Studio")
        self.assertContains(resp, "League Jukebox")
