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



class TestGeneralViewsCase(BaseLeagueTestCase):

    def test_public_and_dashboard_views(self):
        Announcement.objects.create(
            title="Rainout Alert",
            category="weather",
            content="Softball fields closed tonight.",
            is_urgent=True,
        )
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Rainout Alert")

        # Unauthenticated users cannot view partner church directory
        resp_guest_churches = self.client.get(reverse('church_list'))
        self.assertEqual(resp_guest_churches.status_code, 302)
        self.assertRedirects(resp_guest_churches, reverse('home'))

        # Overall / League admins can access partner church directory
        self.client.login(username="admin_user", password="password123")
        resp_admin_churches = self.client.get(reverse('church_list'))
        self.assertEqual(resp_admin_churches.status_code, 200)
        self.assertContains(resp_admin_churches, "First Baptist Fellowship")


    def test_waiver_signing_and_profile(self):
        self.client.login(username="player_user", password="password123")
        self.assertFalse(self.player_user.waiver_signed)

        # 1. Anti-Garbage Test: mismatched signature name should be rejected
        resp_bad = self.client.post(reverse('sign_waiver'), {
            'signature': 'Garbage Asdf Name',
            'agree': True,
        })
        self.assertEqual(resp_bad.status_code, 200)
        self.player_user.refresh_from_db()
        self.assertFalse(self.player_user.waiver_signed)

        # 2. Legitimate matching signature succeeds
        resp_good = self.client.post(reverse('sign_waiver'), {
            'signature': 'player_user',
            'agree': True,
        })
        self.assertEqual(resp_good.status_code, 302)
        self.player_user.refresh_from_db()
        self.assertTrue(self.player_user.waiver_signed)
        self.assertEqual(self.player_user.waiver_signature, 'player_user')


    def test_email_only_registration(self):
        resp = self.client.post(reverse('register'), {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john.doe@fellowship.org',
            'password1': 'Secret12345!',
            'password2': 'Secret12345!',
        })
        self.assertEqual(resp.status_code, 302)
        user = CustomUser.objects.get(email='john.doe@fellowship.org')
        self.assertEqual(user.first_name, 'John')
        self.assertEqual(user.last_name, 'Doe')
        self.assertEqual(user.display_name, 'John Doe')

        # Verify email login (both exact and case-insensitive)
        self.client.logout()
        logged_in = self.client.login(username='john.doe@fellowship.org', password='Secret12345!')
        self.assertTrue(logged_in)
        self.client.logout()
        logged_in_upper = self.client.login(username='JOHN.DOE@FELLOWSHIP.ORG', password='Secret12345!')
        self.assertTrue(logged_in_upper)


    def test_seeded_test_accounts_email_logins(self):
        from django.core.management import call_command
        call_command('create_test_users')

        test_accounts = [
            ('commissioner@sportsball.local', 'sportsball123', 'Paul Andrews'),
            ('coach.grace@sportsball.local', 'sportsball123', 'Caleb Brooks'),
            ('coach.calvary@sportsball.local', 'sportsball123', 'David Miller'),
            ('umpire.bob@sportsball.local', 'sportsball123', 'Bob Jenkins'),
            ('player.josh@sportsball.local', 'sportsball123', 'Josh Peterson'),
            ('freeagent.eli@sportsball.local', 'sportsball123', 'Eli Walker'),
            ('unverified@sportsball.local', 'sportsball123', 'Tommy Test'),
        ]

        for email, pwd, expected_name in test_accounts:
            self.client.logout()
            logged_in = self.client.login(username=email, password=pwd)
            self.assertTrue(logged_in, f"Failed to login with email: {email}")

        # Test testing portal shows all accounts as created with their emails
        resp = self.client.get(reverse('test_users_portal'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Not Created")
        self.assertContains(resp, "coach.grace@sportsball.local")
        self.assertContains(resp, "commissioner@sportsball.local")

        # Test 1-click switch by username or email
        switch_resp = self.client.post(reverse('quick_switch_test_user', args=['coach_grace']))
        self.assertEqual(switch_resp.status_code, 302)
        switch_email_resp = self.client.post(reverse('quick_switch_test_user', args=['coach.calvary@sportsball.local']))
        self.assertEqual(switch_email_resp.status_code, 302)


    def test_church_directory_access_control_and_my_church(self):
        # 1. Unauthenticated guest -> redirects to home
        resp_guest = self.client.get(reverse('church_list'))
        self.assertEqual(resp_guest.status_code, 302)
        self.assertRedirects(resp_guest, reverse('home'))

        # 2. Regular player with home church visiting church_list -> redirected to my_church -> church_detail
        self.client.login(username="player_user", password="password123")
        resp_player = self.client.get(reverse('church_list'))
        self.assertEqual(resp_player.status_code, 302)
        self.assertRedirects(resp_player, reverse('my_church'), target_status_code=302)

        resp_my_church = self.client.get(reverse('my_church'))
        self.assertEqual(resp_my_church.status_code, 302)
        self.assertRedirects(resp_my_church, reverse('church_detail', args=[self.church.id]))

        # 3. Regular player with NO church gets church selector
        self.player_user.church = None
        self.player_user.save(update_fields=['church'])
        resp_select = self.client.get(reverse('my_church'))
        self.assertEqual(resp_select.status_code, 200)
        self.assertContains(resp_select, "Connect to Your Church")


    def test_church_commissioner_creates_team_and_designates_captain(self):
        # Assign coach_user as Church Commissioner for First Baptist Fellowship
        self.church.commissioner = self.coach_user
        self.coach_user.role = 'church_admin'
        self.coach_user.save()
        self.church.save()

        self.client.login(username="coach_user", password="password123")
        self.assertTrue(self.coach_user.is_church_commissioner)

        # Church Commissioner creates team for their church and designates player_user as Captain
        resp_create = self.client.post(
            reverse('create_team', args=[self.season.id]),
            {
                'name': 'Grace Warriors',
                'church': self.church.id,
                'captain': self.player_user.id,
                'team_color': 'Navy Blue',
            }
        )
        self.assertEqual(resp_create.status_code, 302)

        warriors = Team.objects.get(name='Grace Warriors', season=self.season)
        self.assertEqual(warriors.church, self.church)
        self.assertEqual(warriors.captain, self.player_user)
        self.assertIn(self.player_user, warriors.players.all())

        # Verify season registration auto-created for designated captain
        reg = SeasonRegistration.objects.get(season=self.season, player=self.player_user)
        self.assertEqual(reg.status, 'approved')


    def test_overall_commissioner_assigns_church_leader_and_dues(self):
        self.client.login(username="admin_user", password="password123")

        # Assign coach_user as Church Commissioner
        resp_assign = self.client.post(
            reverse('assign_church_commissioner', args=[self.church.id]),
            {'commissioner_id': self.coach_user.id}
        )
        self.assertEqual(resp_assign.status_code, 302)
        self.church.refresh_from_db()
        self.assertEqual(self.church.commissioner, self.coach_user)

        # Toggle dues to paid
        self.assertFalse(self.church.dues_paid)
        resp_dues = self.client.post(reverse('toggle_church_dues', args=[self.church.id]))
        self.assertEqual(resp_dues.status_code, 302)
        self.church.refresh_from_db()
        self.assertTrue(self.church.dues_paid)


    def test_waiver_visibility_restricted_to_captain_and_above(self):
        # Add player_user to team1
        self.team1.players.add(self.player_user)

        # 1. Regular player visits team_detail: Waiver column should NOT appear
        self.client.login(username="player_user", password="password123")
        resp_team_player = self.client.get(reverse('team_detail', args=[self.team1.id]))
        self.assertEqual(resp_team_player.status_code, 200)
        self.assertNotContains(resp_team_player, "<th>Waiver</th>")

        # 2. Regular player visits church_detail: Waiver column should NOT appear
        resp_church_player = self.client.get(reverse('church_detail', args=[self.church.id]))
        self.assertEqual(resp_church_player.status_code, 200)
        self.assertNotContains(resp_church_player, "<th>Waiver</th>")

        # 3. Team captain (coach_user) visits team_detail for team1: Waiver column SHOULD appear
        self.client.login(username="coach_user", password="password123")
        resp_team_captain = self.client.get(reverse('team_detail', args=[self.team1.id]))
        self.assertEqual(resp_team_captain.status_code, 200)
        self.assertContains(resp_team_captain, "<th>Waiver</th>")

        # 4. Overall commissioner (admin_user) visits church_detail: Waiver column SHOULD appear
        self.client.login(username="admin_user", password="password123")
        resp_church_admin = self.client.get(reverse('church_detail', args=[self.church.id]))
        self.assertEqual(resp_church_admin.status_code, 200)
        self.assertContains(resp_church_admin, "<th>Waiver</th>")


    def test_church_members_and_dues_privacy(self):
        church2 = Church.objects.create(name="Calvary Baptist", city="Greenville", state="SC")
        other_player = CustomUser.objects.create_user(
            username="other_player",
            password="password123",
            role="player",
            church=church2,
        )

        # 1. other_player from church2 viewing church1: member directory and dues are HIDDEN
        self.client.login(username="other_player", password="password123")
        resp_out = self.client.get(reverse('church_detail', args=[self.church.id]))
        self.assertEqual(resp_out.status_code, 200)
        self.assertNotContains(resp_out, "Congregation Athletes &amp; Members")
        self.assertContains(resp_out, "Internal congregation member directory is private")
        self.assertNotContains(resp_out, "League Dues")

        # 2. player_user (belongs to church1) viewing church1: members VISIBLE, but dues and waivers HIDDEN
        self.client.login(username="player_user", password="password123")
        resp_in = self.client.get(reverse('church_detail', args=[self.church.id]))
        self.assertEqual(resp_in.status_code, 200)
        self.assertContains(resp_in, "Congregation Athletes &amp; Members")
        self.assertNotContains(resp_in, "<th>Waiver</th>")
        self.assertNotContains(resp_in, "League Dues")

        # 3. admin_user (overall commissioner) viewing church1: members, waivers, and dues VISIBLE
        self.client.login(username="admin_user", password="password123")
        resp_adm = self.client.get(reverse('church_detail', args=[self.church.id]))
        self.assertEqual(resp_adm.status_code, 200)
        self.assertContains(resp_adm, "Congregation Athletes &amp; Members")
        self.assertContains(resp_adm, "<th>Waiver</th>")
        self.assertContains(resp_adm, "Dues Pending")


    def test_profile_waiver_privacy(self):
        # player_user has signed waiver
        self.player_user.waiver_signed = True
        self.player_user.save()

        # other_player views player_user profile -> Waiver Signed is NOT shown
        other = CustomUser.objects.create_user(username="viewer", password="password123", role="player")
        self.client.login(username="viewer", password="password123")
        resp_view = self.client.get(reverse('player_detail', args=[self.player_user.id]))
        self.assertEqual(resp_view.status_code, 200)
        self.assertNotContains(resp_view, "Waiver Signed")

        # player_user views own profile -> Waiver Signed IS shown
        self.client.login(username="player_user", password="password123")
        resp_self = self.client.get(reverse('profile'))
        self.assertEqual(resp_self.status_code, 200)
        self.assertContains(resp_self, "Waiver Signed")


    def test_free_agent_requires_login(self):
        # Unauthenticated request redirects to login
        resp = self.client.get(reverse('free_agent_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp.url)


    def test_coach_cannot_post_urgent_announcement(self):
        self.client.login(username="coach_user", password="password123")
        resp = self.client.post(reverse('create_announcement'), {
            'title': 'Coach Announcement',
            'category': 'general',
            'content': 'Practice moved to 7pm.',
            'league': self.league.id,
            'is_urgent': True,
        })
        self.assertEqual(resp.status_code, 302)
        ann = Announcement.objects.get(title='Coach Announcement')
        self.assertFalse(ann.is_urgent)  # Forced to False by permission enforcement


    def test_church_invite_onboarding_and_zero_step_waiver(self):
        # 1. Test church invite link
        self.assertTrue(bool(self.church.invite_code))
        invite_url = reverse('join_church_invite', args=[self.church.invite_code])

        # New user visits invite URL -> redirects to register with ?church_invite
        resp_anon = self.client.get(invite_url)
        self.assertEqual(resp_anon.status_code, 302)
        self.assertIn(f'church_invite={self.church.invite_code}', resp_anon.url)

        # Register user with church_invite and agree_waiver
        resp_reg = self.client.post(reverse('register'), {
            'first_name': 'Pastor',
            'last_name': 'Mark',
            'email': 'pastor.mark@gracefellowship.org',
            'password1': 'sportsball123',
            'password2': 'sportsball123',
            'agree_waiver': 'on',
            'church_invite': self.church.invite_code,
        }, follow=True)
        self.assertEqual(resp_reg.status_code, 200)

        new_user = CustomUser.objects.get(email='pastor.mark@gracefellowship.org')
        self.assertTrue(new_user.waiver_signed)
        self.church.refresh_from_db()
        self.assertEqual(self.church.commissioner, new_user)
        self.assertEqual(new_user.role, 'church_admin')


    def test_unsigned_user_home_dashboard(self):
        unsigned_user = CustomUser.objects.create_user(
            username="unverified@sportsball.local",
            email="unverified@sportsball.local",
            password="password123",
            role="player",
            waiver_signed=False,
            church=self.church
        )
        self.client.login(username="unverified@sportsball.local", password="password123")
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Liability Waiver &amp; Sportsmanship Covenant Required")
        self.assertContains(resp, "Sign Waiver Now")



    def test_home_dashboard_schedule_scoping_and_announcement_badge(self):
        # 1. Unassigned free agent views dashboard: No upcoming schedule, no redundant announcements card
        eli = CustomUser.objects.create_user(
            username="eli_walker", password="password123", role="player", is_free_agent=True
        )
        self.client.login(username="eli_walker", password="password123")
        resp_eli = self.client.get(reverse('home'))
        self.assertEqual(resp_eli.status_code, 200)
        self.assertNotContains(resp_eli, 'id="seeAllScheduleBtn"')
        self.assertNotContains(resp_eli, 'id="tabViewUpcoming"')

        # 2. Announcement created -> Sidebar displays alert badge
        Announcement.objects.create(
            title="Spring Registration Closes Friday",
            content="Please get your team dues in.",
            author=self.admin_user,
        )
        resp_badge = self.client.get(reverse('home'))
        self.assertContains(resp_badge, 'title="1 new announcement"')

        # 3. Rostered player views dashboard: Sees upcoming schedule with 'See All ->' and 'Recent Scores' tab
        self.team1.players.add(self.player_user)
        Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=timezone.now() + timedelta(days=4), location="Diamond 1"
        )
        self.client.login(username="player_user", password="password123")
        resp_rostered = self.client.get(reverse('home'))
        self.assertEqual(resp_rostered.status_code, 200)
        self.assertContains(resp_rostered, 'id="seeAllScheduleBtn"')
        self.assertContains(resp_rostered, 'See All &rarr;')
        self.assertContains(resp_rostered, 'id="btnTabResults"')

