"""
Tests for production hardening, timezone middleware, health checks,
S3 storage fallback, emergency safety rosters, and auto-finalization.
"""
from datetime import timedelta
import io
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from core.models import Church
from leagues.models import Game, League, Season, Team
from leagues.tests.base import BaseLeagueTestCase
from users.models import CustomUser
from users.models.user import validate_audio_file_size


class TestProductionHardening(BaseLeagueTestCase):
    """Verifies edge-case hardening, /healthz, safety rosters, timezone middleware, and S3."""

    def test_healthz_endpoint(self):
        """Container health probe returns 200 OK with healthy DB status."""
        resp = self.client.get(reverse('healthz'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['database'], 'healthy')
        self.assertIn('timestamp', data)

    def test_user_timezone_middleware(self):
        """User timezone cookie activates ZoneInfo per-request."""
        self.client.cookies['sportsball_timezone'] = 'America/Chicago'
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        # Verify current active timezone matches
        self.assertEqual(str(timezone.get_current_timezone()), 'America/Chicago')

    def test_validate_audio_file_size(self):
        """Audio validator allows files <= 8MB and rejects files > 8MB."""
        # 1MB file - valid
        valid_file = SimpleUploadedFile("song.mp3", b"0" * (1 * 1024 * 1024), content_type="audio/mpeg")
        try:
            validate_audio_file_size(valid_file)
        except ValidationError:
            self.fail("validate_audio_file_size raised ValidationError on 1MB file")

        # 9MB file - invalid
        oversized_file = SimpleUploadedFile("big_song.mp3", b"0" * (9 * 1024 * 1024), content_type="audio/mpeg")
        with self.assertRaises(ValidationError) as ctx:
            validate_audio_file_size(oversized_file)
        self.assertIn("Audio file size cannot exceed 8 MB", str(ctx.exception))

    def test_team_safety_roster_access_control(self):
        """
        Safety roster sheet displays emergency contacts to captains & commishes,
        while denying unauthorized players.
        """
        # 1. Unauthenticated -> 302 to login
        url = reverse('team_safety_roster', kwargs={'team_id': self.team1.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp.url)

        # 2. Team captain -> 200 OK
        self.client.force_login(self.coach_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Emergency &amp; Safety Roster")
        self.assertContains(resp, self.team1.name)

        # 3. Unrelated player -> 302 redirect with permission error
        unrelated_player = CustomUser.objects.create_user(
            username='stranger_player',
            email='stranger@sportsball.local',
            password='pass',
            role='player'
        )
        self.client.force_login(unrelated_player)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse('team_detail', kwargs={'team_id': self.team1.id}))

        # 4. League Commissioner / Overall Admin -> 200 OK
        self.client.force_login(self.admin_user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.team1.name)

    def test_auto_finalize_stale_scores_management_command(self):
        """Management command auto-confirms pending games submitted > 48h ago."""
        # Create game submitted 50 hours ago
        stale_game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now() - timedelta(days=3),
            location="Field 1",
            status='pending_confirmation',
            team1_score=5,
            team2_score=3,
            score_submitted_by=self.coach_user,
            score_submitted_at=timezone.now() - timedelta(hours=50),
            score_confirmed=False
        )

        # Create game submitted 2 hours ago (fresh)
        fresh_game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now() - timedelta(hours=3),
            location="Field 2",
            status='pending_confirmation',
            team1_score=7,
            team2_score=6,
            score_submitted_by=self.coach_user,
            score_submitted_at=timezone.now() - timedelta(hours=2),
            score_confirmed=False
        )

        out = io.StringIO()
        call_command('auto_finalize_scores', '--hours=48', stdout=out)
        output = out.getvalue()
        self.assertIn("Successfully auto-finalized 1 stale pending game(s)", output)

        stale_game.refresh_from_db()
        fresh_game.refresh_from_db()

        self.assertEqual(stale_game.status, 'completed')
        self.assertTrue(stale_game.score_confirmed)

        self.assertEqual(fresh_game.status, 'pending_confirmation')
        self.assertFalse(fresh_game.score_confirmed)

    def test_s3_storage_settings_detection(self):
        """Verify STORAGES default configuration adapts based on environment variables."""
        from django.conf import settings
        # In current test run, AWS_STORAGE_BUCKET_NAME is unset -> FileSystemStorage
        self.assertEqual(settings.STORAGES['default']['BACKEND'], 'django.core.files.storage.FileSystemStorage')
