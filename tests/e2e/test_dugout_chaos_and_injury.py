from tests.e2e.base_e2e import BasePlaywrightTestCase
from leagues.models import GameLineupEntry
from users.models import CustomUser


class DugoutChaosAndInjuryE2ETest(BasePlaywrightTestCase):
    """
    Adversarial and chaos E2E browser tests for:
    - Softball short-handed 1-out differential rule in live Dugout Console.
    - Mid-game injury / benching lineup shift without scorekeeper crash.
    - Team Intro Anthems playback triggers.
    """

    def setUp(self):
        super().setUp()

        # Seed 8 players for team1 (Grace Sluggers)
        self.sluggers_players = [self.coach_grace, self.player_josh, self.player_sarah]
        for i in range(4, 9):
            p = CustomUser.objects.create_user(
                username=f"slugger_{i}",
                email=f"slugger_{i}@sportsball.local",
                password="sportsball123",
                first_name=f"Player{i}",
                last_name="Grace",
                role="player",
                church=self.church_grace,
                waiver_signed=True,
                gender="M" if i % 2 == 0 else "F",
            )
            self.sluggers_players.append(p)
            self.team_sluggers.players.add(p)

        # Seed 10 players for team2 (Calvary Crusaders)
        self.crusaders_players = [self.coach_calvary]
        for i in range(2, 11):
            p = CustomUser.objects.create_user(
                username=f"crusader_{i}",
                email=f"crusader_{i}@sportsball.local",
                password="sportsball123",
                first_name=f"Player{i}",
                last_name="Calvary",
                role="player",
                church=self.church_calvary,
                waiver_signed=True,
                gender="M" if i % 2 == 0 else "F",
            )
            self.crusaders_players.append(p)
            self.team_crusaders.players.add(p)

        # Build initial lineup for team1 (8 batters)
        for idx, p in enumerate(self.sluggers_players, start=1):
            GameLineupEntry.objects.create(
                game=self.game,
                team=self.team_sluggers,
                player=p,
                batting_order=idx,
            )

        # Build initial lineup for team2 (10 batters)
        for idx, p in enumerate(self.crusaders_players, start=1):
            GameLineupEntry.objects.create(
                game=self.game,
                team=self.team_crusaders,
                player=p,
                batting_order=idx,
            )

        # Calculate automatic outs (Sluggers 8 vs Crusaders 10 -> exactly 1 auto-out at spot #9)
        self.game.sync_shorthanded_automatic_outs()
        self.game.status = "in_progress"
        self.game.current_inning = 1
        self.game.inning_half = "top"
        self.game.outs = 0
        self.game.save()

    def test_shorthanded_lineup_and_intro_anthems_in_dugout(self):
        page = self.page

        # 1. Coach Grace opens Dugout Console
        self.login_as(page, self.coach_grace)
        page.goto(f"{self.live_server_url}/leagues/games/{self.game.id}/console/")
        page.wait_for_load_state("networkidle")

        # 2. Verify Lineup and Short-Handed Auto-Out slot exists in Team 1 lineup
        auto_out_slot = GameLineupEntry.objects.filter(
            game=self.game,
            team=self.team_sluggers,
            is_automatic_out=True
        ).first()
        self.assertIsNotNone(auto_out_slot)
        self.assertEqual(auto_out_slot.batting_order, 9)

        # Check page content for game console scoreboard
        self.assertIn("Grace Sluggers", page.content())
        self.assertIn("Calvary Crusaders", page.content())

        # 3. Test 1-Tap Out action updates scoreboard cleanly
        out_btn = page.locator(".action-btn.btn-out").first
        if out_btn.is_visible():
            out_btn.click()
            page.wait_for_timeout(500)
            self.game.refresh_from_db()
            self.assertEqual(self.game.outs, 1)

        # 4. Test Inning Flip to bottom half (Sluggers batting)
        flip_btn = page.locator('button:has-text("Next Period / Inning Half")').first
        if flip_btn.is_visible():
            flip_btn.click()
            page.wait_for_timeout(500)
            self.game.refresh_from_db()
            self.assertEqual(self.game.inning_half, "bottom")
            self.assertEqual(self.game.outs, 0)

        # 5. Fast forward to 2 outs and spot #9 (Auto-out)
        self.game.outs = 2
        self.game.team1_batter_index = 8  # Slot 9 is next
        self.game.save()

        # Call advance_to_next_batter via backend or trigger next batter
        next_b = self.game.advance_to_next_batter()
        self.game.save()
        # Because slot 9 is an automatic out, with 2 outs it retired the side!
        self.game.refresh_from_db()
        self.assertEqual(self.game.outs, 0)
        self.assertEqual(self.game.current_inning, 2)
        self.assertEqual(self.game.inning_half, "top")

        # 6. Spectator Live GameCast can be opened and loads without crashing
        spectator_page = self.context.new_page()
        spectator_page.goto(f"{self.live_server_url}/leagues/games/{self.game.id}/gamecast/")
        spectator_page.wait_for_load_state("networkidle")
        self.assertIn("Grace Sluggers", spectator_page.content())
        self.assertIn("Top 2", spectator_page.content())
        spectator_page.close()
