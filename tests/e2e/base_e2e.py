import os
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

from datetime import date, timedelta
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from playwright.sync_api import sync_playwright

from core.models import Church, SystemSetting, BackupConfiguration
from leagues.models import League, Season, Team, Game, SeasonRegistration
from users.models import CustomUser

IPHONE_VIEWPORT = {'width': 390, 'height': 844}
DESKTOP_VIEWPORT = {'width': 1280, 'height': 800}


class BasePlaywrightTestCase(StaticLiveServerTestCase):
    """Base class providing a headless Chromium browser instance against Django's live server."""

    @classmethod
    def setUpClass(cls):
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.context = self.browser.new_context(viewport=DESKTOP_VIEWPORT)
        self.page = self.context.new_page()

        # Seed standard church and test entities
        self.church_grace = Church.objects.create(
            name="Grace Fellowship Church",
            denomination="Baptist",
            city="Greenville",
            state="SC",
        )
        self.church_calvary = Church.objects.create(
            name="Calvary Chapel Fellowship",
            denomination="Non-Denominational",
            city="Spartanburg",
            state="SC",
        )

        # Common test users
        self.admin_user = CustomUser.objects.create_superuser(
            username="commissioner",
            email="commissioner@sportsball.local",
            password="sportsball123",
            first_name="Paul",
            last_name="Andrews",
            role="admin",
            waiver_signed=True,
            waiver_signature="Paul Andrews",
        )
        self.coach_grace = CustomUser.objects.create_user(
            username="coach_grace",
            email="coach.grace@sportsball.local",
            password="sportsball123",
            first_name="Caleb",
            last_name="Brooks",
            role="coach",
            church=self.church_grace,
            waiver_signed=True,
            waiver_signature="Caleb Brooks",
            gender="M",
        )
        self.coach_calvary = CustomUser.objects.create_user(
            username="coach_calvary",
            email="coach.calvary@sportsball.local",
            password="sportsball123",
            first_name="David",
            last_name="Miller",
            role="coach",
            church=self.church_calvary,
            waiver_signed=True,
            waiver_signature="David Miller",
            gender="M",
        )
        self.referee_bob = CustomUser.objects.create_user(
            username="umpire_bob",
            email="umpire.bob@sportsball.local",
            password="sportsball123",
            first_name="Bob",
            last_name="Jenkins",
            role="referee",
            waiver_signed=True,
            waiver_signature="Bob Jenkins",
            gender="M",
        )
        self.player_josh = CustomUser.objects.create_user(
            username="player_josh",
            email="player.josh@sportsball.local",
            password="sportsball123",
            first_name="Josh",
            last_name="Peterson",
            role="player",
            church=self.church_grace,
            jersey_number=12,
            waiver_signed=True,
            waiver_signature="Josh Peterson",
            gender="M",
        )
        self.player_sarah = CustomUser.objects.create_user(
            username="player_sarah",
            email="player.sarah@sportsball.local",
            password="sportsball123",
            first_name="Sarah",
            last_name="Jenkins",
            role="player",
            church=self.church_grace,
            jersey_number=7,
            waiver_signed=True,
            waiver_signature="Sarah Jenkins",
            gender="F",
        )
        self.player_unverified = CustomUser.objects.create_user(
            username="unverified_test",
            email="unverified@sportsball.local",
            password="sportsball123",
            first_name="Tommy",
            last_name="Test",
            role="player",
            church=self.church_grace,
            waiver_signed=False,
            gender="M",
        )

        # Assign church commissioner
        self.church_grace.commissioner = self.coach_grace
        self.church_grace.save(update_fields=['commissioner'])

        # League & Season
        self.league = League.objects.create(
            name="Grace Rec Softball League",
            sport="softball",
            description="Co-ed church slowpitch softball fellowship",
            admin=self.admin_user,
        )
        self.season = Season.objects.create(
            league=self.league,
            name="Summer 2026 Co-Ed",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=60),
            current=True,
            registration_open=True,
            registration_fee=35.00,
            max_roster_size=20,
        )

        # Teams
        self.team_sluggers = Team.objects.create(
            name="Grace Sluggers",
            league=self.league,
            season=self.season,
            church=self.church_grace,
            captain=self.coach_grace,
            team_color="Navy Blue",
        )
        self.team_sluggers.players.add(self.coach_grace, self.player_josh, self.player_sarah, self.player_unverified)

        self.team_crusaders = Team.objects.create(
            name="Calvary Crusaders",
            league=self.league,
            season=self.season,
            church=self.church_calvary,
            captain=self.coach_calvary,
            team_color="Crimson Red",
        )
        self.team_crusaders.players.add(self.coach_calvary)

        # Scheduled Game
        self.game = Game.objects.create(
            season=self.season,
            team1=self.team_sluggers,
            team2=self.team_crusaders,
            date=timezone.now() + timedelta(hours=2),
            location="Heritage Park Field #1",
            status="scheduled",
        )

    def tearDown(self):
        self.context.close()
        super().tearDown()

    def login_as(self, page, user, password="sportsball123"):
        """Performs authentic web login via the login page."""
        page.context.clear_cookies()
        page.goto(f"{self.live_server_url}/users/login/")
        page.fill('input[name="username"]', user.email or user.username)
        page.fill('input[name="password"]', password)
        page.locator('form button:has-text("Log In")').click()
        page.wait_for_load_state("networkidle")
