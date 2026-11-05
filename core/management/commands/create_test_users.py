from django.core.management.base import BaseCommand
from core.models import Church
from users.models import CustomUser


TEST_USERS = [
    # (username, password, first_name, last_name, role, church_name, jersey, walkup_title, is_fa, waiver)
    ("commissioner", "sportsball123", "Paul", "Andrews", "admin", "Grace Fellowship Church", 99, "Ballpark Organ Fanfare", False, True),
    ("coach_grace", "sportsball123", "Caleb", "Brooks", "coach", "Grace Fellowship Church", 34, "Victory Walk-Up Fanfare", False, True),
    ("coach_calvary", "sportsball123", "David", "Miller", "coach", "Calvary Baptist Church", 23, "Eye of the Tiger (Intro)", False, True),
    ("coach_redeemer", "sportsball123", "Luke", "Vance", "coach", "Redeemer Presbyterian", 11, "Chariots of Fire Theme", False, True),
    ("umpire_bob", "sportsball123", "Bob", "Jenkins", "referee", "Grace Fellowship Church", None, "", False, True),
    ("player_josh", "sportsball123", "Josh", "Peterson", "player", "Grace Fellowship Church", 12, "Awesome God (Brass Riff)", False, True),
    ("player_micah", "sportsball123", "Micah", "Thompson", "player", "Calvary Baptist Church", 3, "Strike Up the Band", False, True),
    ("player_ethan", "sportsball123", "Ethan", "Reed", "player", "Redeemer Presbyterian", 21, "Home Run Organ Rally", False, True),
    ("player_sarah", "sportsball123", "Sarah", "Collins", "player", "Hope Community Methodist", 7, "Grand Slam Anthem", False, True),
    ("free_agent_eli", "sportsball123", "Eli", "Walker", "player", "Grace Fellowship Church", 9, "", True, False),
    ("free_agent_hannah", "sportsball123", "Hannah", "Davis", "player", "Hope Community Methodist", 4, "", True, False),
    ("unverified_test", "sportsball123", "Tommy", "Test", "player", None, 18, "", False, False),
]


class Command(BaseCommand):
    help = "Creates a roster of pre-configured local test users with known credentials for offline testing"

    def add_arguments(self, parser):
        parser.add_argument(
            '--password',
            type=str,
            default='sportsball123',
            help='Universal password for all created test accounts (default: sportsball123)'
        )

    def handle(self, *args, **options):
        password = options['password']
        churches_map = {c.name: c for c in Church.objects.all()}

        created_count = 0
        updated_count = 0

        self.stdout.write(self.style.NOTICE("Setting up local testing accounts (no email setup required)..."))

        for uname, _, fname, lname, role, ch_name, jersey, song_title, is_fa, waiver in TEST_USERS:
            church = churches_map.get(ch_name) if ch_name else None
            user, created = CustomUser.objects.get_or_create(
                username=uname,
                defaults={
                    'email': f"{uname}@sportsball.local",
                    'first_name': fname,
                    'last_name': lname,
                    'role': role,
                    'church': church,
                    'jersey_number': jersey,
                    'is_free_agent': is_fa,
                    'waiver_signed': waiver,
                    'waiver_signature': f"{fname} {lname}" if waiver else "",
                    'walkup_song_title': song_title,
                    'walkup_start_seconds': 0,
                    'walkup_duration_seconds': 10,
                    'is_staff': (role == 'admin'),
                    'is_superuser': (role == 'admin'),
                }
            )

            # Always set the testing password
            user.set_password(password)
            user.role = role
            user.church = church
            user.jersey_number = jersey
            user.is_free_agent = is_fa
            user.waiver_signed = waiver
            if waiver:
                user.waiver_signature = f"{fname} {lname}"
            if role == 'admin':
                user.is_staff = True
                user.is_superuser = True
            user.save()

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done! {created_count} test users created, {updated_count} test users updated.\n"
            f"Universal Password: '{password}'\n\n"
            f"Ready-to-use accounts:\n"
            f" • Commissioner / League Admin : commissioner / {password}\n"
            f" • Coach (Grace Sluggers)      : coach_grace  / {password}\n"
            f" • Coach (Calvary Lions)       : coach_calvary / {password}\n"
            f" • Umpire / Referee            : umpire_bob   / {password}\n"
            f" • Player (Rostered w/ Waiver) : player_josh  / {password}\n"
            f" • Free Agent (Looking for Tm) : free_agent_eli / {password}\n"
            f" • Unsigned Waiver Player      : unverified_test / {password}"
        ))
