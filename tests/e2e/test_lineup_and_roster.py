from tests.e2e.base_e2e import BasePlaywrightTestCase
from leagues.models import GameLineupEntry


class LineupAndRosterE2ETest(BasePlaywrightTestCase):
    """Verifies Coach Lineup Builder, 7:3 Co-ed Ratio Advisory Banner, and Printable Dugout Cards."""

    def test_lineup_builder_and_coed_ratio_advisory(self):
        page = self.page
        self.login_as(page, self.coach_grace)

        lineup_url = f"{self.live_server_url}/leagues/games/{self.game.id}/lineup/{self.team_sluggers.id}/"
        page.goto(lineup_url)
        page.wait_for_load_state("networkidle")

        # 1. Verify Lineup Builder rendered
        self.assertIn("Lineup", page.content())
        self.assertIn("Grace Sluggers", page.content())

        # 2. Check Co-ed Ratio Advisory Banner
        # In our setup: Grace Sluggers has 3 males (Caleb, Josh, Tommy) and 1 female (Sarah)
        # Ratio requires at least 3 female players in co-ed slowpitch softball
        content = page.content()
        self.assertIn("Co-Ed Player Ratio Advisory", content)
        self.assertIn("female", content.lower())

        # 3. Add female players to test compliant co-ed ratio & balanced order
        from users.models import CustomUser
        female_player2 = CustomUser.objects.create_user(
            username="player_rebecca", email="rebecca@sportsball.local",
            password="sportsball123", first_name="Rebecca", last_name="Taylor",
            role="player", church=self.church_grace, gender="F", waiver_signed=True
        )
        female_player3 = CustomUser.objects.create_user(
            username="player_hannah", email="hannah@sportsball.local",
            password="sportsball123", first_name="Hannah", last_name="Scott",
            role="player", church=self.church_grace, gender="F", waiver_signed=True
        )
        self.team_sluggers.players.add(female_player2, female_player3)

        # Clear existing entries and create fresh compliant alternating order: 3 males, 3 females
        GameLineupEntry.objects.filter(game=self.game, team=self.team_sluggers).delete()
        alternating_roster = [
            (self.coach_grace, "OF"),
            (self.player_sarah, "1B"),
            (self.player_josh, "SS"),
            (female_player2, "2B"),
            (self.player_unverified, "3B"),
            (female_player3, "C"),
        ]
        for idx, (player_obj, pos) in enumerate(alternating_roster, start=1):
            GameLineupEntry.objects.create(
                game=self.game,
                team=self.team_sluggers,
                player=player_obj,
                batting_order=idx,
                field_position=pos,
                is_present=True,
            )

        page.reload()
        page.wait_for_load_state("networkidle")

        # Verify co-ed ratio indicator shows Balanced/Compliant and 3 Female
        updated_content = page.content()
        self.assertIn("Co-Ed Batting Order: Balanced / Compliant", updated_content)
        self.assertIn("3 Female", updated_content)

        # 4. Verify Printable Dugout Lineup Card
        print_url = f"{self.live_server_url}/leagues/games/{self.game.id}/lineup/{self.team_sluggers.id}/print/"
        page.goto(print_url)
        page.wait_for_load_state("networkidle")

        self.assertIn("Print Official Lineup Card", page.content())
        self.assertIn("Official Starting Lineup", page.content())
        self.assertIn("Grace Sluggers", page.content())
        self.assertIn("Josh Peterson", page.content())
        self.assertIn("Sarah Jenkins", page.content())

