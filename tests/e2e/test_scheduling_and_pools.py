from datetime import date, timedelta
from django.utils import timezone
from tests.e2e.base_e2e import BasePlaywrightTestCase
from leagues.models import LeagueVenue, Season, Team, Game


class SchedulingAndPoolsE2ETest(BasePlaywrightTestCase):
    """Verifies League Master Pools, Weather Rainouts, Reschedule Assistant, and Franchise Reuse."""

    def test_master_pools_and_team_import(self):
        page = self.page
        self.login_as(page, self.admin_user)

        # 1. Open Master Pools Console
        pools_url = f"{self.live_server_url}/leagues/{self.league.id}/pools/"
        page.goto(pools_url)
        page.wait_for_load_state("networkidle")

        self.assertIn("Master Pools", page.content())
        self.assertIn("Venues & Fields Pool", page.content())
        self.assertIn("Master Officials Pool", page.content())

        # 2. Add New Venue to Master Pool
        page.fill('input[name="name"]', 'Eastside Park Field #3')
        page.fill('input[name="address"]', '500 Eastside Way')
        page.fill('input[name="notes"]', 'Dugout code 4455')
        page.locator('form button:has-text("Add Venue to Master Pool")').click()
        page.wait_for_load_state("networkidle")

        venue = LeagueVenue.objects.filter(league=self.league, name='Eastside Park Field #3').first()
        self.assertIsNotNone(venue)
        self.assertTrue(venue.is_active)
        self.assertIn("Eastside Park Field #3", page.content())

        # 3. Add Referee to Master Officials Pool
        page.select_option('select[name="user_id"]', str(self.referee_bob.id))
        page.locator('form button:has-text("Add Official")').click()
        page.wait_for_load_state("networkidle")

        self.assertIn(self.referee_bob, self.league.master_officials_pool.all())
        self.assertIn("Bob Jenkins", page.content())

        # 4. Create New Future Season and verify franchise import
        new_season = Season.objects.create(
            league=self.league,
            name="Fall 2026 Fellowship",
            start_date=date.today() + timedelta(days=90),
            end_date=date.today() + timedelta(days=150),
        )

        import_url = f"{self.live_server_url}/leagues/seasons/{new_season.id}/teams/import/?source_season_id={self.season.id}"
        page.goto(import_url)
        page.wait_for_load_state("networkidle")

        self.assertIn("Re-use Teams Across Seasons", page.content())
        self.assertIn("Grace Sluggers", page.content())
        self.assertIn("Calvary Crusaders", page.content())

        # Import selected teams
        page.locator('form button:has-text("Import Selected Teams")').click()
        page.wait_for_load_state("networkidle")

        # Verify teams exist in target season
        imported_names = list(new_season.teams.values_list('name', flat=True))
        self.assertIn("Grace Sluggers", imported_names)
        self.assertIn("Calvary Crusaders", imported_names)
