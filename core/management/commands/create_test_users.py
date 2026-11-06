from django.core.management.base import BaseCommand
from core.models import Church
from users.models import CustomUser
from leagues.models import Team, SeasonRegistration


TEST_USERS = [
    # (username, email, password, first_name, last_name, role, church_name, jersey, walkup_title, is_fa, waiver)
    ("commissioner", "commissioner@sportsball.local", "sportsball123", "Paul", "Andrews", "admin", "Grace Fellowship Church", 99, "Ballpark Organ Fanfare", False, True),
    ("coach_grace", "coach.grace@sportsball.local", "sportsball123", "Caleb", "Brooks", "church_admin", "Grace Fellowship Church", 34, "Victory Walk-Up Fanfare", False, True),
    ("coach_calvary", "coach.calvary@sportsball.local", "sportsball123", "David", "Miller", "church_admin", "Calvary Baptist Church", 23, "Eye of the Tiger (Intro)", False, True),
    ("coach_redeemer", "coach.redeemer@sportsball.local", "sportsball123", "Luke", "Vance", "coach", "Redeemer Presbyterian", 11, "Chariots of Fire Theme", False, True),
    ("umpire_bob", "umpire.bob@sportsball.local", "sportsball123", "Bob", "Jenkins", "referee", "Grace Fellowship Church", None, "", False, True),
    ("player_josh", "player.josh@sportsball.local", "sportsball123", "Josh", "Peterson", "player", "Grace Fellowship Church", 12, "Awesome God (Brass Riff)", False, True),
    ("player_micah", "player.micah@sportsball.local", "sportsball123", "Micah", "Thompson", "player", "Calvary Baptist Church", 3, "Strike Up the Band", False, True),
    ("player_ethan", "player.ethan@sportsball.local", "sportsball123", "Ethan", "Reed", "player", "Redeemer Presbyterian", 21, "Home Run Organ Rally", False, True),
    ("player_sarah", "player.sarah@sportsball.local", "sportsball123", "Sarah", "Collins", "player", "Hope Community Methodist", 7, "Grand Slam Anthem", False, True),
    ("free_agent_eli", "freeagent.eli@sportsball.local", "sportsball123", "Eli", "Walker", "player", "Grace Fellowship Church", 9, "", True, False),
    ("free_agent_hannah", "freeagent.hannah@sportsball.local", "sportsball123", "Hannah", "Davis", "player", "Hope Community Methodist", 4, "", True, False),
    ("unverified_test", "unverified@sportsball.local", "sportsball123", "Tommy", "Test", "player", None, 18, "", False, False),
]


class Command(BaseCommand):
    help = "Creates a roster of pre-configured local test users with email logins for zero-friction testing"

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

        self.stdout.write(self.style.NOTICE("Setting up local testing accounts with email logins..."))

        user_objects = {}
        for uname, email, _, fname, lname, role, ch_name, jersey, song_title, is_fa, waiver in TEST_USERS:
            church = churches_map.get(ch_name) if ch_name else None

            # Look up by either email or username to update cleanly
            user = CustomUser.objects.filter(username=uname).first() or CustomUser.objects.filter(email__iexact=email).first()

            if user:
                created = False
                user.email = email
                user.username = uname
                user.first_name = fname
                user.last_name = lname
            else:
                created = True
                user = CustomUser(
                    username=uname,
                    email=email,
                    first_name=fname,
                    last_name=lname,
                )

            user.role = role
            user.church = church
            user.jersey_number = jersey
            user.is_free_agent = is_fa
            user.waiver_signed = waiver
            user.waiver_signature = f"{fname} {lname}" if waiver else ""
            user.walkup_song_title = song_title
            user.walkup_start_seconds = 0
            user.walkup_duration_seconds = 10
            user.is_staff = (role in ('admin', 'committee'))
            user.is_superuser = (role == 'admin')
            user.set_password(password)
            user.save()

            user_objects[uname] = user
            if created:
                created_count += 1
            else:
                updated_count += 1

        # Designate Church Commissioners and Dues on partner churches
        grace_church = Church.objects.filter(name__icontains="Grace Fellowship").first()
        calvary_church = Church.objects.filter(name__icontains="Calvary Baptist").first()

        if grace_church and user_objects.get("coach_grace"):
            grace_church.commissioner = user_objects.get("coach_grace")
            grace_church.dues_paid = True
            grace_church.save(update_fields=['commissioner', 'dues_paid'])

        if calvary_church and user_objects.get("coach_calvary"):
            calvary_church.commissioner = user_objects.get("coach_calvary")
            calvary_church.dues_paid = True
            calvary_church.save(update_fields=['commissioner', 'dues_paid'])

        # Automatically link test users to teams and rosters if demo teams exist
        grace_sluggers = Team.objects.filter(name__icontains="Grace Sluggers").first()
        calvary_crusaders = Team.objects.filter(name__icontains="Calvary").first()

        if grace_sluggers:
            coach_grace = user_objects.get("coach_grace")
            player_josh = user_objects.get("player_josh")
            commissioner = user_objects.get("commissioner")
            if coach_grace:
                grace_sluggers.captain = coach_grace
                grace_sluggers.players.add(coach_grace)
                grace_sluggers.save(update_fields=['captain'])
            if player_josh:
                grace_sluggers.players.add(player_josh)
                SeasonRegistration.objects.update_or_create(
                    season=grace_sluggers.season,
                    player=player_josh,
                    defaults={'preferred_team': grace_sluggers, 'status': 'approved', 'waiver_agreed': True}
                )
            if commissioner:
                grace_sluggers.players.add(commissioner)

        if calvary_crusaders:
            coach_calvary = user_objects.get("coach_calvary")
            player_micah = user_objects.get("player_micah")
            if coach_calvary:
                calvary_crusaders.captain = coach_calvary
                calvary_crusaders.players.add(coach_calvary)
                calvary_crusaders.save(update_fields=['captain'])
            if player_micah:
                calvary_crusaders.players.add(player_micah)
                SeasonRegistration.objects.update_or_create(
                    season=calvary_crusaders.season,
                    player=player_micah,
                    defaults={'preferred_team': calvary_crusaders, 'status': 'approved', 'waiver_agreed': True}
                )

        self.stdout.write(self.style.SUCCESS(
            f"Done! {created_count} test users created, {updated_count} test users updated.\n"
            f"Universal Password: '{password}'\n\n"
            f"Ready-to-use Email Accounts:\n"
            f" • Overall Commissioner   : commissioner@sportsball.local\n"
            f" • Grace Church Commish   : coach.grace@sportsball.local\n"
            f" • Calvary Church Commish : coach.calvary@sportsball.local\n"
            f" • Umpire / Referee       : umpire.bob@sportsball.local\n"
            f" • Rostered Player        : player.josh@sportsball.local\n"
            f" • Free Agent Player      : freeagent.eli@sportsball.local\n"
            f" • Unsigned Waiver Test   : unverified@sportsball.local\n"
        ))
