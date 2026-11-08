from tests.e2e.base_e2e import BasePlaywrightTestCase
from leagues.models import LeagueVenue, PlayerDisciplinaryRecord, GameSportsmanshipRating


class DisciplineVenuesAndConductE2ETest(BasePlaywrightTestCase):
    """Verifies Disciplinary Hub, Lineup Lockout, Venue Hotline, and Sportsmanship Ratings."""

    def test_disciplinary_lineup_lockout_and_field_hotline(self):
        page = self.page

        # =====================================================================
        # 1. Disciplinary Ruling & Lineup Builder Hard-Lock
        # =====================================================================
        # Overall Commissioner logs in and issues a 1-game suspension to player_josh
        self.login_as(page, self.admin_user)
        discipline_url = f"{self.live_server_url}/leagues/{self.league.id}/discipline/"
        page.goto(discipline_url)
        page.wait_for_load_state("networkidle")

        self.assertIn("Conduct Hub", page.content())
        self.assertIn("Disciplinary", page.content())

        # Fill disciplinary form
        page.select_option('select[name="player_id"]', str(self.player_josh.id))
        page.select_option('select[name="team_id"]', str(self.team_sluggers.id))
        page.select_option('select[name="penalty_type"]', 'game_count')
        page.fill('input[name="games_suspended_total"]', '1')
        page.fill('textarea[name="reason"]', 'Technical foul for unsportsmanlike bench arguing')
        page.locator('form button:has-text("Record Disciplinary Action")').click()
        page.wait_for_load_state("networkidle")

        # Verify active penalty appears on disciplinary dashboard
        self.assertIn("Active Penalties", page.content())
        self.assertIn("Josh Peterson", page.content())
        self.assertIn("1 remaining", page.content())

        # Coach Grace logs in and views Lineup Builder -> Josh Peterson is locked!
        self.login_as(page, self.coach_grace)
        lineup_url = f"{self.live_server_url}/leagues/games/{self.game.id}/lineup/{self.team_sluggers.id}/"
        page.goto(lineup_url)
        page.wait_for_load_state("networkidle")

        # Verify ineligibility notice is displayed
        content = page.content()
        self.assertIn("Ineligible", content)
        self.assertIn("Suspended", content)
        self.assertIn("Locked", content)

        # =====================================================================
        # 2. Venue Condition Hotline on Home Page
        # =====================================================================
        # Create venue with unplayable status
        venue = LeagueVenue.objects.create(
            league=self.league,
            name="Heritage Field #3",
            status="closed",
            status_note="Standing water in infield from rain"
        )

        # Navigate to public home page
        page.goto(f"{self.live_server_url}/")
        page.wait_for_load_state("networkidle")

        home_content = page.content()
        self.assertIn("Field Conditions", home_content)
        self.assertIn("Heritage Field #3", home_content)
        self.assertIn("Standing water", home_content)

        # =====================================================================
        # 3. Post-Game Fellowship & Sportsmanship Rating Scorecard
        # =====================================================================
        # Mark game as completed
        self.game.status = 'completed'
        self.game.team1_score = 9
        self.game.team2_score = 7
        self.game.score_confirmed = True
        self.game.save()

        # Coach Calvary logs in and views game detail to evaluate Grace Sluggers
        self.login_as(page, self.coach_calvary)
        game_detail_url = f"{self.live_server_url}/leagues/games/{self.game.id}/"
        page.goto(game_detail_url)
        page.wait_for_load_state("networkidle")

        self.assertIn("Sportsmanship Scorecard", page.content())
        self.assertIn("Christian Fellowship", page.content())

        # Submit sportsmanship evaluation for Grace Sluggers
        page.select_option('select[name="rated_team_id"]', str(self.team_sluggers.id))
        page.select_option('select[name="score"]', '5')
        page.select_option('select[name="respect_for_officials"]', '5')
        page.select_option('select[name="bench_conduct"]', '5')
        page.fill('textarea[name="notes"]', 'Exemplary fellowship and encouragement')
        page.locator('form button:has-text("Submit Sportsmanship Rating")').click()
        page.wait_for_load_state("networkidle")

        # Verify rating appears on game detail
        self.assertIn("5★", page.content())
        self.assertIn("Exemplary fellowship and encouragement", page.content())

        # =====================================================================
        # 4. Committee Sportsmanship Dashboard & Configurable Thresholds
        # =====================================================================
        self.login_as(page, self.admin_user)
        sportsmanship_url = f"{self.live_server_url}/leagues/{self.league.id}/sportsmanship/"
        page.goto(sportsmanship_url)
        page.wait_for_load_state("networkidle")

        dash_content = page.content()
        self.assertIn("Sportsmanship Dashboard", dash_content)
        self.assertIn("Christian Fellowship", dash_content)
        self.assertIn("Grace Sluggers", dash_content)
        self.assertIn("Good Standing", dash_content)

        # Tune thresholds
        page.fill('input[name="sportsmanship_good_threshold"]', '4.75')
        page.fill('input[name="sportsmanship_review_threshold"]', '3.50')
        page.locator('form button:has-text("Update Standards")').click()
        page.wait_for_load_state("networkidle")

        self.assertIn("Updated league sportsmanship thresholds", page.content())
