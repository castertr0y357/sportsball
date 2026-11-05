from django.core.management import call_command
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from users.models import CustomUser
from core.models import Church


TEST_ROLES_CATALOG = [
    {
        'username': 'commissioner',
        'name': 'Paul Andrews (Commissioner)',
        'role': 'League Admin',
        'badge': 'badge-danger',
        'desc': 'Full administrative control, schedule generator, playoff brackets, announcements.',
    },
    {
        'username': 'coach_grace',
        'name': 'Caleb Brooks (Grace Coach)',
        'role': 'Coach / Captain',
        'badge': 'badge-primary',
        'desc': 'Home dugout operator, lineup check-in, walk-up music DJ.',
    },
    {
        'username': 'coach_calvary',
        'name': 'David Miller (Calvary Coach)',
        'role': 'Coach / Captain',
        'badge': 'badge-primary',
        'desc': 'Away dugout operator, opposing team captain.',
    },
    {
        'username': 'umpire_bob',
        'name': 'Bob Jenkins (Umpire / Ref)',
        'role': 'Referee / Scorekeeper',
        'badge': 'badge-warning',
        'desc': 'Field official with permissions to update scores and log player stats.',
    },
    {
        'username': 'player_josh',
        'name': 'Josh Peterson (Player)',
        'role': 'Rostered Player',
        'badge': 'badge-success',
        'desc': 'Grace Sluggers #12, waiver verified, custom walk-up fanfare.',
    },
    {
        'username': 'free_agent_eli',
        'name': 'Eli Walker (Free Agent)',
        'role': 'Free Agent',
        'badge': 'badge',
        'desc': 'Unassigned individual player waiting for church team draft.',
    },
    {
        'username': 'unverified_test',
        'name': 'Tommy Test (No Waiver)',
        'role': 'Unsigned Player',
        'badge': 'badge-warning',
        'desc': 'Player with unsigned waiver to test captain dugout warnings.',
    },
]


def test_users_portal(request):
    """
    In-App Test User Portal:
    - View, create, and 1-click switch between test accounts without terminal commands.
    - Add custom test players/coaches directly from the browser on Kubernetes.
    """
    # Auto-seed basic test users if none exist yet
    if not CustomUser.objects.filter(username__in=['commissioner', 'coach_grace']).exists():
        try:
            call_command('create_test_users')
        except Exception:
            pass

    test_users = CustomUser.objects.filter(
        username__in=[r['username'] for r in TEST_ROLES_CATALOG]
    ).select_related('church')
    users_by_uname = {u.username: u for u in test_users}

    catalog = []
    for item in TEST_ROLES_CATALOG:
        user_obj = users_by_uname.get(item['username'])
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


def quick_switch_test_user(request, username):
    """1-Click switch login session to any test user from the web UI."""
    if request.method != 'POST':
        return redirect('test_users_portal')

    user = get_object_or_404(CustomUser, username=username)
    login(request, user)
    messages.success(request, f"⚡ Switched active session to {user.display_name} ({user.get_role_display()})!")
    return redirect('home')


def create_in_app_test_user(request):
    """Create a new custom test user directly from the web browser without email confirmation."""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip().lower()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        role = request.POST.get('role', 'player')
        church_id = request.POST.get('church_id')
        jersey = request.POST.get('jersey_number')
        password = request.POST.get('password', 'sportsball123')
        sign_waiver = bool(request.POST.get('sign_waiver'))
        is_free_agent = bool(request.POST.get('is_free_agent'))
        walkup_title = request.POST.get('walkup_song_title', '').strip()

        if not username:
            messages.error(request, "Username is required.")
            return redirect('test_users_portal')

        if CustomUser.objects.filter(username=username).exists():
            messages.error(request, f"User '{username}' already exists.")
            return redirect('test_users_portal')

        church = Church.objects.filter(id=church_id).first() if church_id else None

        user = CustomUser.objects.create(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=f"{username}@sportsball.local",
            role=role,
            church=church,
            jersey_number=int(jersey) if jersey and jersey.isdigit() else None,
            is_free_agent=is_free_agent,
            waiver_signed=sign_waiver,
            waiver_signature=f"{first_name} {last_name}".strip() if sign_waiver else "",
            walkup_song_title=walkup_title,
            is_staff=(role == 'admin'),
            is_superuser=(role == 'admin'),
        )
        user.set_password(password or 'sportsball123')
        user.save()

        # Auto-login as the freshly created user if requested
        if request.POST.get('auto_login'):
            login(request, user)
            messages.success(request, f"Created and logged in as {user.display_name}!")
            return redirect('home')

        messages.success(request, f"Test user '{user.username}' created successfully!")
    return redirect('test_users_portal')


def reset_all_demo_data_in_app(request):
    """1-Click button to re-seed demo data and test users on Kubernetes."""
    if request.method == 'POST':
        try:
            call_command('seed_demo_data')
            call_command('create_test_users')
            messages.success(request, "Demo churches, leagues, rosters, and test accounts re-seeded successfully!")
        except Exception as e:
            messages.error(request, f"Failed to seed demo data: {e}")
    return redirect('test_users_portal')
