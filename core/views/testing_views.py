"""
In-app test user sandbox portal and instant role-switching views.
All views are implemented as Class-Based Views.
"""

from __future__ import annotations
from django.core.management import call_command
from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import render, redirect
from django.db.models import Q
from django.views.generic import View
from users.models import CustomUser
from core.models import Church
from users.backends import LEGACY_EMAIL_ALIASES

TEST_ROLES_CATALOG = [
    # --- COMMISSIONERS ---
    {
        'username': 'commissioner',
        'email': 'commissioner@sportsball.local',
        'name': 'Paul Andrews (Overall Commish)',
        'category': 'Commissioners',
        'role': 'Overall Commissioner',
        'badge': 'badge-danger',
        'desc': 'Platform-wide administrator with full access to bylaws, leagues, and churches.',
    },
    {
        'username': 'commish_softball',
        'email': 'commish.softball@sportsball.local',
        'name': 'Paul Henderson (Softball Commish)',
        'category': 'Commissioners',
        'role': 'Softball Commissioner',
        'badge': 'badge-danger',
        'desc': 'Manages the 6-team Spring/Summer Church Softball league.',
    },
    {
        'username': 'commish_basketball',
        'email': 'commish.basketball@sportsball.local',
        'name': 'Marcus Bradley (Hoops Commish)',
        'category': 'Commissioners',
        'role': 'Basketball Commissioner',
        'badge': 'badge-danger',
        'desc': 'Manages the 3-team Men\'s & Co-Ed Fellowship Basketball league.',
    },
    {
        'username': 'commish_football',
        'email': 'commish.football@sportsball.local',
        'name': 'Brian Taylor (Football Commish)',
        'category': 'Commissioners',
        'role': 'Football Commissioner',
        'badge': 'badge-danger',
        'desc': 'Manages the 3-team Autumn Fellowship Flag Football league.',
    },

    # --- SOFTBALL COACHES (6 TEAMS) ---
    {
        'username': 'coach_sluggers',
        'email': 'coach.sluggers@sportsball.local',
        'name': 'Caleb Brooks (Grace Sluggers Coach)',
        'category': 'Softball Coaches (15 Players/Team)',
        'role': 'Coach / Church Admin',
        'badge': 'badge-primary',
        'desc': 'Grace Fellowship Team 1. Lineup card, roster, and live dugout console (alias: coach.grace@sportsball.local).',
    },
    {
        'username': 'coach_overcomers',
        'email': 'coach.overcomers@sportsball.local',
        'name': 'Thomas Bradley (Grace Overcomers Coach)',
        'category': 'Softball Coaches (15 Players/Team)',
        'role': 'Coach',
        'badge': 'badge-primary',
        'desc': 'Grace Fellowship Team 2. Lineup card and game scoring.',
    },
    {
        'username': 'coach_glory',
        'email': 'coach.glory@sportsball.local',
        'name': 'Steven Vance (Grace Glory Coach)',
        'category': 'Softball Coaches (15 Players/Team)',
        'role': 'Coach',
        'badge': 'badge-primary',
        'desc': 'Grace Fellowship Team 3. Lineup card and game scoring.',
    },
    {
        'username': 'coach_crusaders',
        'email': 'coach.crusaders@sportsball.local',
        'name': 'David Miller (Calvary Crusaders Coach)',
        'category': 'Softball Coaches (15 Players/Team)',
        'role': 'Coach / Church Admin',
        'badge': 'badge-primary',
        'desc': 'Calvary Baptist Team 1. Lineup card and live dugout console.',
    },
    {
        'username': 'coach_lions',
        'email': 'coach.lions@sportsball.local',
        'name': 'Robert Hayes (Calvary Lions Coach)',
        'category': 'Softball Coaches (15 Players/Team)',
        'role': 'Coach',
        'badge': 'badge-primary',
        'desc': 'Calvary Baptist Team 2. Lineup card and roster manager.',
    },
    {
        'username': 'coach_fire',
        'email': 'coach.fire@sportsball.local',
        'name': 'Capt. Robert Briggs (Station 7 Smoke Eaters Coach)',
        'category': 'Softball Coaches (15 Players/Team)',
        'role': 'Coach',
        'badge': 'badge-primary',
        'desc': 'Greenville Fire & Rescue Department (Outside Partner Team).',
    },

    # --- BASKETBALL COACHES (3 TEAMS UNDER REDEEMER) ---
    {
        'username': 'coach_royals',
        'email': 'coach.royals@sportsball.local',
        'name': 'Luke Vance (Redeemer Royals Coach)',
        'category': 'Basketball Coaches (11 Players/Team)',
        'role': 'Coach / Church Admin',
        'badge': 'badge-primary',
        'desc': 'Redeemer Presbyterian Hoops Team 1.',
    },
    {
        'username': 'coach_thunder',
        'email': 'coach.thunder@sportsball.local',
        'name': 'Mark Davis (Redeemer Thunder Coach)',
        'category': 'Basketball Coaches (11 Players/Team)',
        'role': 'Coach',
        'badge': 'badge-primary',
        'desc': 'Redeemer Presbyterian Hoops Team 2.',
    },
    {
        'username': 'coach_covenant',
        'email': 'coach.covenant@sportsball.local',
        'name': 'James Wilson (Redeemer Covenant Coach)',
        'category': 'Basketball Coaches (11 Players/Team)',
        'role': 'Coach',
        'badge': 'badge-primary',
        'desc': 'Redeemer Presbyterian Hoops Team 3.',
    },

    # --- FOOTBALL COACHES (3 TEAMS UNDER HOPE COMMUNITY) ---
    {
        'username': 'coach_warriors',
        'email': 'coach.warriors@sportsball.local',
        'name': 'Sarah Jenkins (Hope Warriors Coach)',
        'category': 'Flag Football Coaches (16 Players/Team)',
        'role': 'Coach / Church Admin',
        'badge': 'badge-primary',
        'desc': 'Hope Community Flag Football Team 1.',
    },
    {
        'username': 'coach_ironmen',
        'email': 'coach.ironmen@sportsball.local',
        'name': 'Douglas Carter (Hope Ironmen Coach)',
        'category': 'Flag Football Coaches (16 Players/Team)',
        'role': 'Coach',
        'badge': 'badge-primary',
        'desc': 'Hope Community Flag Football Team 2.',
    },
    {
        'username': 'coach_defenders',
        'email': 'coach.defenders@sportsball.local',
        'name': 'Anthony Woods (Hope Defenders Coach)',
        'category': 'Flag Football Coaches (16 Players/Team)',
        'role': 'Coach',
        'badge': 'badge-primary',
        'desc': 'Hope Community Flag Football Team 3.',
    },

    # --- FEATURED PLAYERS (1 PER TEAM = 12 PLAYERS) ---
    {
        'username': 'player_sluggers',
        'email': 'player.sluggers@sportsball.local',
        'name': 'Josh Peterson (Grace Sluggers #12)',
        'category': 'Featured Team Players',
        'role': 'Player',
        'badge': 'badge-success',
        'desc': 'Grace Sluggers batter #12, walkup audio fanfare configured.',
    },
    {
        'username': 'player_overcomers',
        'email': 'player.overcomers@sportsball.local',
        'name': 'Luke Harper (Grace Overcomers #8)',
        'category': 'Featured Team Players',
        'role': 'Player',
        'badge': 'badge-success',
        'desc': 'Grace Overcomers player #8.',
    },
    {
        'username': 'player_glory',
        'email': 'player.glory@sportsball.local',
        'name': 'Timothy Evans (Grace Glory #11)',
        'category': 'Featured Team Players',
        'role': 'Player',
        'badge': 'badge-success',
        'desc': 'Grace Glory player #11.',
    },
    {
        'username': 'player_crusaders',
        'email': 'player.crusaders@sportsball.local',
        'name': 'Micah Thompson (Calvary Crusaders #3)',
        'category': 'Featured Team Players',
        'role': 'Player',
        'badge': 'badge-success',
        'desc': 'Calvary Crusaders batter #3, walkup fanfare configured.',
    },
    {
        'username': 'player_lions',
        'email': 'player.lions@sportsball.local',
        'name': 'Aaron Cooper (Calvary Lions #9)',
        'category': 'Featured Team Players',
        'role': 'Player',
        'badge': 'badge-success',
        'desc': 'Calvary Lions player #9.',
    },
    {
        'username': 'player_fire',
        'email': 'player.fire@sportsball.local',
        'name': 'Jake Sullivan (Station 7 Smoke Eaters #7)',
        'category': 'Featured Team Players',
        'role': 'Player',
        'badge': 'badge-success',
        'desc': 'Greenville Fire & Rescue Department #7.',
    },
    {
        'username': 'player_royals',
        'email': 'player.royals@sportsball.local',
        'name': 'Ethan Reed (Redeemer Royals #21)',
        'category': 'Featured Team Players',
        'role': 'Player',
        'badge': 'badge-success',
        'desc': 'Redeemer Royals basketball player #21.',
    },
    {
        'username': 'player_thunder',
        'email': 'player.thunder@sportsball.local',
        'name': 'Daniel Hayes (Redeemer Thunder #4)',
        'category': 'Featured Team Players',
        'role': 'Player',
        'badge': 'badge-success',
        'desc': 'Redeemer Thunder basketball player #4.',
    },
    {
        'username': 'player_covenant',
        'email': 'player.covenant@sportsball.local',
        'name': 'Benjamin Price (Redeemer Covenant #24)',
        'category': 'Featured Team Players',
        'role': 'Player',
        'badge': 'badge-success',
        'desc': 'Redeemer Covenant basketball player #24.',
    },
    {
        'username': 'player_warriors',
        'email': 'player.warriors@sportsball.local',
        'name': 'Sarah Collins (Hope Warriors #15)',
        'category': 'Featured Team Players',
        'role': 'Player',
        'badge': 'badge-success',
        'desc': 'Hope Warriors flag football player #15.',
    },
    {
        'username': 'player_ironmen',
        'email': 'player.ironmen@sportsball.local',
        'name': 'Gabriel Murphy (Hope Ironmen #10)',
        'category': 'Featured Team Players',
        'role': 'Player',
        'badge': 'badge-success',
        'desc': 'Hope Ironmen flag football player #10.',
    },
    {
        'username': 'player_defenders',
        'email': 'player.defenders@sportsball.local',
        'name': 'Jordan Bell (Hope Defenders #22)',
        'category': 'Featured Team Players',
        'role': 'Player',
        'badge': 'badge-success',
        'desc': 'Hope Defenders flag football player #22.',
    },

    # --- OFFICIALS & TESTING PERSONAS ---
    {
        'username': 'umpire_bob',
        'email': 'umpire.bob@sportsball.local',
        'name': 'Bob Jenkins (Umpire / Referee)',
        'category': 'Officials & Testing Personas',
        'role': 'Referee / Scorekeeper',
        'badge': 'badge-warning',
        'desc': 'Field official with permissions to score games and approve rosters.',
    },
    {
        'username': 'free_agent_eli',
        'email': 'freeagent.eli@sportsball.local',
        'name': 'Eli Walker (Free Agent)',
        'category': 'Officials & Testing Personas',
        'role': 'Free Agent',
        'badge': 'badge',
        'desc': 'Unassigned individual player waiting for team placement.',
    },
    {
        'username': 'free_agent_hannah',
        'email': 'freeagent.hannah@sportsball.local',
        'name': 'Hannah Davis (Free Agent)',
        'category': 'Officials & Testing Personas',
        'role': 'Free Agent',
        'badge': 'badge',
        'desc': 'Hope Community free agent awaiting team assignment.',
    },
    {
        'username': 'unverified_test',
        'email': 'unverified@sportsball.local',
        'name': 'Tommy Test (No Waiver)',
        'category': 'Officials & Testing Personas',
        'role': 'Unsigned Player',
        'badge': 'badge-warning',
        'desc': 'Player with unsigned waiver to test captain dugout warnings.',
    },
]


class TestUsersPortalView(View):
    """In-App Test User Portal: View, create, and 1-click switch between test accounts."""

    def get(self, request):
        required_emails = [r['email'] for r in TEST_ROLES_CATALOG]
        existing_count = CustomUser.objects.filter(
            Q(email__in=required_emails) | Q(username__in=[r['username'] for r in TEST_ROLES_CATALOG])
        ).count()

        if existing_count < len(TEST_ROLES_CATALOG):
            try:
                call_command('create_test_users')
            except Exception:
                pass

        test_users = CustomUser.objects.filter(
            Q(email__in=required_emails) | Q(username__in=[r['username'] for r in TEST_ROLES_CATALOG])
        ).select_related('church')

        users_by_email = {u.email.lower(): u for u in test_users}
        users_by_uname = {u.username.lower(): u for u in test_users}

        catalog = []
        for item in TEST_ROLES_CATALOG:
            user_obj = users_by_email.get(item['email'].lower()) or users_by_uname.get(item['username'].lower())
            catalog.append({
                **item,
                'user': user_obj,
                'exists': user_obj is not None,
            })

        churches = Church.objects.all()
        return render(request, 'core/test_users_portal.html', {
            'catalog': catalog,
            'churches': churches,
            'roles': CustomUser.ROLE_CHOICES,
        })


class QuickSwitchTestUserView(View):
    """Instantly switches active authenticated session to targeted test account."""

    def get(self, request, username: str):
        return self._do_switch(request, username)

    def post(self, request, username: str):
        return self._do_switch(request, username)

    def _do_switch(self, request, username: str):
        uname_clean = str(username).strip()
        query = Q(username__iexact=uname_clean) | Q(email__iexact=uname_clean)

        alias = LEGACY_EMAIL_ALIASES.get(uname_clean.lower())
        if alias:
            alias_prefix = alias.split('@')[0] if '@' in alias else alias
            query |= Q(username__iexact=alias) | Q(email__iexact=alias) | Q(username__iexact=alias_prefix)

        user = CustomUser.objects.filter(query).first()

        if not user:
            messages.error(request, f"User '{username}' not found.")
            return redirect('test_users_portal')

        login(request, user, backend='users.backends.EmailOrUsernameModelBackend')
        messages.success(request, f"⚡ Switched active session to {user.display_name} ({user.get_role_display()})!")
        return redirect('home')


class CreateInAppTestUserView(View):
    """Creates a custom role-specific user in the database without terminal commands."""

    def post(self, request):
        email = request.POST.get('email', '').strip().lower()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        role = request.POST.get('role', 'player')
        church_id = request.POST.get('church_id')
        jersey = request.POST.get('jersey_number')
        password = request.POST.get('password', 'sportsball123')
        sign_waiver = bool(request.POST.get('sign_waiver'))
        is_free_agent = bool(request.POST.get('is_free_agent'))
        walkup_title = request.POST.get('walkup_song_title', '').strip()

        if not email:
            messages.error(request, "Email address is required.")
            return redirect('test_users_portal')

        if CustomUser.objects.filter(email__iexact=email).exists():
            messages.error(request, f"User with email '{email}' already exists.")
            return redirect('test_users_portal')

        church = Church.objects.filter(id=church_id).first() if church_id else None

        user = CustomUser.objects.create(
            username=email[:150],
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
            church=church,
            jersey_number=int(jersey) if jersey and jersey.isdigit() else None,
            is_free_agent=is_free_agent,
            waiver_signed=sign_waiver,
            waiver_signature=f"{first_name} {last_name}".strip() if sign_waiver else "",
            walkup_song_title=walkup_title,
            is_staff=(role in ('admin', 'committee')),
            is_superuser=(role == 'admin'),
        )
        user.set_password(password or 'sportsball123')
        user.save()

        if role == 'church_admin' and church:
            church.commissioner = user
            church.save(update_fields=['commissioner'])

        if request.POST.get('auto_login'):
            login(request, user, backend='users.backends.EmailOrUsernameModelBackend')
            messages.success(request, f"Created and logged in as {user.display_name}!")
            return redirect('home')

        messages.success(request, f"Test user '{user.email}' created successfully!")
        return redirect('test_users_portal')


class ResetAllDemoDataInAppView(View):
    """Re-executes the seed_demo_data and create_test_users management commands."""

    def post(self, request):
        try:
            call_command('seed_demo_data')
            call_command('create_test_users')
            messages.success(request, "Demo churches, leagues, rosters, and test accounts re-seeded successfully!")
        except Exception as e:
            messages.error(request, f"Failed to seed demo data: {e}")
        return redirect('test_users_portal')
