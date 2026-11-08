"""
Base test case providing shared models, users, teams, and setup fixtures.
"""

from datetime import date, timedelta
from django.test import TestCase
from core.models import Church
from users.models import CustomUser
from leagues.models import League, Season, Team


class BaseLeagueTestCase(TestCase):
    """Common test fixture initializing churches, users, leagues, seasons, and teams."""

    def setUp(self):
        self.church = Church.objects.create(
            name="First Baptist Fellowship",
            denomination="Baptist",
            city="Greenville",
            state="SC",
        )
        self.admin_user = CustomUser.objects.create_user(
            username="admin_user",
            password="password123",
            role="admin",
            church=self.church,
        )
        self.coach_user = CustomUser.objects.create_user(
            username="coach_user",
            password="password123",
            role="coach",
            church=self.church,
        )
        self.player_user = CustomUser.objects.create_user(
            username="player_user",
            password="password123",
            role="player",
            church=self.church,
        )

        self.league = League.objects.create(
            name="Fellowship Basketball League",
            sport="basketball",
            description="Weekly church basketball",
            admin=self.admin_user,
        )
        self.season = Season.objects.create(
            league=self.league,
            name="Winter 2026",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=60),
            current=True,
            registration_open=True,
            registration_fee=25.00,
        )
        self.team1 = Team.objects.create(
            name="Eagles",
            league=self.league,
            season=self.season,
            church=self.church,
            captain=self.coach_user,
        )
        self.team2 = Team.objects.create(
            name="Lions",
            league=self.league,
            season=self.season,
            church=self.church,
            captain=self.admin_user,
        )
        self.team3 = Team.objects.create(
            name="Anchors",
            league=self.league,
            season=self.season,
            church=self.church,
            captain=self.coach_user,
        )
        self.team4 = Team.objects.create(
            name="Royals",
            league=self.league,
            season=self.season,
            church=self.church,
            captain=self.admin_user,
        )
