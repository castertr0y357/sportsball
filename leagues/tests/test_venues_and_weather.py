import json
from datetime import date, timedelta
from django.urls import reverse
from django.utils import timezone
from core.models import Church, Announcement
from users.models import CustomUser
from leagues.models import (
    League, Season, Team, SeasonRegistration, Game,
    LeagueVenue, PlayerDisciplinaryRecord, GameSportsmanshipRating,
    GameOfficialAssignment, GameLineupEntry
)
from stats.models import PlayerGameStat
from leagues.tests.base import BaseLeagueTestCase



class TestVenuesAndWeatherCase(BaseLeagueTestCase):

    def test_rainout_today_and_auto_makeup(self):
        today = timezone.localdate()
        today_dt = timezone.now()
        game_today = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=today_dt,
            location="Diamond #1",
            status="scheduled",
            game_type="regular",
            week_number=1
        )

        # Non-commissioner cannot rain out
        self.client.login(username="player_user", password="password123")
        resp_denied = self.client.post(reverse('rainout_today_games', args=[self.season.id]))
        self.assertEqual(resp_denied.status_code, 302)
        game_today.refresh_from_db()
        self.assertEqual(game_today.status, 'scheduled')
        self.assertEqual(game_today.week_number, 1)

        # Commissioner rains out today -> auto moves to makeup week
        self.client.login(username="admin_user", password="password123")
        resp_rainout = self.client.post(reverse('rainout_today_games', args=[self.season.id]), {
            'action': 'reschedule_makeup',
            'date': today.strftime('%Y-%m-%d'),
        })
        self.assertEqual(resp_rainout.status_code, 302)

        game_today.refresh_from_db()
        self.assertEqual(game_today.status, 'scheduled')
        self.assertEqual(game_today.week_number, 2)
        self.assertGreater(game_today.date, today_dt)
        self.assertIn("Rescheduled from rainout", game_today.notes)


    def test_reschedule_rainouts(self):
        rainout_game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Heritage Park", status='rainout'
        )

        self.client.login(username="admin_user", password="password123")
        makeup_date = (timezone.now() + timedelta(days=14)).strftime('%Y-%m-%d')
        resp = self.client.post(reverse('reschedule_rainouts', args=[self.season.id]), {
            'selected_games': [rainout_game.id],
            'target_date': makeup_date,
            'target_time': '10:00',
            'interval_minutes': 60
        })
        self.assertEqual(resp.status_code, 302)

        rainout_game.refresh_from_db()
        self.assertEqual(rainout_game.status, 'scheduled')
        self.assertEqual(rainout_game.date.strftime('%Y-%m-%d'), makeup_date)
        self.assertIn("Rescheduled makeup", rainout_game.notes)



    def test_master_venues_pool(self):
        self.client.login(username="admin_user", password="password123")
        # Add venue to pool
        resp = self.client.post(reverse('add_league_venue', args=[self.league.id]), {
            'name': 'Heritage Diamond #3',
            'address': '100 Main St',
            'notes': 'Dugout gate code 1234'
        })
        self.assertEqual(resp.status_code, 302)
        venue = LeagueVenue.objects.get(league=self.league, name='Heritage Diamond #3')
        self.assertTrue(venue.is_active)

        # Toggle active
        resp = self.client.post(reverse('toggle_league_venue', args=[self.league.id, venue.id]))
        self.assertEqual(resp.status_code, 302)
        venue.refresh_from_db()
        self.assertFalse(venue.is_active)

        # Delete venue
        resp = self.client.post(reverse('delete_league_venue', args=[self.league.id, venue.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(LeagueVenue.objects.filter(id=venue.id).exists())


    def test_venue_status_update_and_game_relocation(self):
        """Verifies 1-click field relocation atomically updates scheduled games."""
        self.client.login(username="admin_user", password="password123")
        field1 = LeagueVenue.objects.create(league=self.league, name="Diamond #1", status="open")
        field2 = LeagueVenue.objects.create(league=self.league, name="Turf Complex #2", status="open")

        game = Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now(), location="Diamond #1", venue=field1, status='scheduled'
        )

        # Update field1 to closed due to standing water
        resp = self.client.post(reverse('update_venue_status', args=[field1.id]), {
            'status': 'closed',
            'status_note': 'Infield flooded from overnight storm'
        })
        self.assertEqual(resp.status_code, 302)
        field1.refresh_from_db()
        self.assertEqual(field1.status, 'closed')
        self.assertEqual(field1.status_note, 'Infield flooded from overnight storm')

        # Relocate games from field1 to field2
        resp = self.client.post(reverse('relocate_venue_games', args=[field1.id]), {
            'action_type': 'relocate',
            'new_venue_id': str(field2.id),
            'reason': 'Heavy standing water'
        })
        self.assertEqual(resp.status_code, 302)

        game.refresh_from_db()
        self.assertEqual(game.venue, field2)
        self.assertEqual(game.location, "Turf Complex #2")

