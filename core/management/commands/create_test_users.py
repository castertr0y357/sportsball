from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db.models import Q
from core.models import Church
from users.models import CustomUser
from leagues.models import Team, SeasonRegistration


TEST_USERS = [
    # --- COMMISSIONERS ---
    ("commissioner", "commissioner@sportsball.local", "sportsball123", "Paul", "Andrews", "admin", "Grace Fellowship Church", 99, "Ballpark Organ Fanfare", False, True, "Overall League Administrator"),
    ("commish_softball", "commish.softball@sportsball.local", "sportsball123", "Paul", "Henderson", "admin", "Grace Fellowship Church", 90, "Softball Commission Fanfare", False, True, "Softball League Commissioner"),
    ("commish_basketball", "commish.basketball@sportsball.local", "sportsball123", "Marcus", "Bradley", "admin", "Redeemer Presbyterian", 91, "Court Buzzer Fanfare", False, True, "Basketball League Commissioner"),
    ("commish_football", "commish.football@sportsball.local", "sportsball123", "Brian", "Taylor", "admin", "Hope Community Methodist", 92, "First Down Fanfare", False, True, "Flag Football Commissioner"),

    # --- SOFTBALL COACHES (6 TEAMS) ---
    ("coach_sluggers", "coach.sluggers@sportsball.local", "sportsball123", "Caleb", "Brooks", "church_admin", "Grace Fellowship Church", 34, "Victory Walk-Up Fanfare", False, True, "Grace Sluggers Coach (Grace 1)"),
    ("coach_overcomers", "coach.overcomers@sportsball.local", "sportsball123", "Thomas", "Bradley", "coach", "Grace Fellowship Church", 45, "Ballpark Rally Theme", False, True, "Grace Overcomers Coach (Grace 2)"),
    ("coach_glory", "coach.glory@sportsball.local", "sportsball123", "Steven", "Vance", "coach", "Grace Fellowship Church", 50, "Glory Land Riff", False, True, "Grace Glory Coach (Grace 3)"),
    ("coach_crusaders", "coach.crusaders@sportsball.local", "sportsball123", "David", "Miller", "church_admin", "Calvary Baptist Church", 23, "Eye of the Tiger (Intro)", False, True, "Calvary Crusaders Coach (Calvary 1)"),
    ("coach_lions", "coach.lions@sportsball.local", "sportsball123", "Robert", "Hayes", "coach", "Calvary Baptist Church", 32, "Lion Roar Fanfare", False, True, "Calvary Lions Coach (Calvary 2)"),
    ("coach_fire", "coach.fire@sportsball.local", "sportsball123", "Robert", "Briggs", "coach", "Greenville Fire & Rescue", 77, "Siren & Horn Fanfare", False, True, "Station 7 Smoke Eaters Coach (Fire Dept)"),

    # --- BASKETBALL COACHES (3 TEAMS UNDER REDEEMER PRESBYTERIAN) ---
    ("coach_royals", "coach.royals@sportsball.local", "sportsball123", "Luke", "Vance", "church_admin", "Redeemer Presbyterian", 11, "Chariots of Fire Theme", False, True, "Redeemer Royals Coach (Hoops 1)"),
    ("coach_thunder", "coach.thunder@sportsball.local", "sportsball123", "Mark", "Davis", "coach", "Redeemer Presbyterian", 30, "Thunderstruck Organ Hook", False, True, "Redeemer Thunder Coach (Hoops 2)"),
    ("coach_covenant", "coach.covenant@sportsball.local", "sportsball123", "James", "Wilson", "coach", "Redeemer Presbyterian", 15, "Covenant Victory Chime", False, True, "Redeemer Covenant Coach (Hoops 3)"),

    # --- FLAG FOOTBALL COACHES (3 TEAMS UNDER HOPE COMMUNITY) ---
    ("coach_warriors", "coach.warriors@sportsball.local", "sportsball123", "Sarah", "Jenkins", "church_admin", "Hope Community Methodist", 7, "Warrior Drum March", False, True, "Hope Warriors Coach (Football 1)"),
    ("coach_ironmen", "coach.ironmen@sportsball.local", "sportsball123", "Douglas", "Carter", "coach", "Hope Community Methodist", 88, "Iron Sharpens Iron Fanfare", False, True, "Hope Ironmen Coach (Football 2)"),
    ("coach_defenders", "coach.defenders@sportsball.local", "sportsball123", "Anthony", "Woods", "coach", "Hope Community Methodist", 54, "Fortress Defense March", False, True, "Hope Defenders Coach (Football 3)"),

    # --- FEATURED PLAYERS (1 PER TEAM = 12 PLAYERS) ---
    ("player_sluggers", "player.sluggers@sportsball.local", "sportsball123", "Josh", "Peterson", "player", "Grace Fellowship Church", 12, "Awesome God (Brass Riff)", False, True, "Grace Sluggers Featured Player"),
    ("player_overcomers", "player.overcomers@sportsball.local", "sportsball123", "Luke", "Harper", "player", "Grace Fellowship Church", 8, "Sweet Child O Mine Fanfare", False, True, "Grace Overcomers Featured Player"),
    ("player_glory", "player.glory@sportsball.local", "sportsball123", "Timothy", "Evans", "player", "Grace Fellowship Church", 11, "Faithful Charge Theme", False, True, "Grace Glory Featured Player"),
    ("player_crusaders", "player.crusaders@sportsball.local", "sportsball123", "Micah", "Thompson", "player", "Calvary Baptist Church", 3, "Strike Up the Band", False, True, "Calvary Crusaders Featured Player"),
    ("player_lions", "player.lions@sportsball.local", "sportsball123", "Aaron", "Cooper", "player", "Calvary Baptist Church", 9, "Roar of the Lion", False, True, "Calvary Lions Featured Player"),
    ("player_fire", "player.fire@sportsball.local", "sportsball123", "Jake", "Sullivan", "player", "Greenville Fire & Rescue", 7, "Backdraft Stadium Anthem", False, True, "Station 7 Smoke Eaters Featured Player"),
    ("player_royals", "player.royals@sportsball.local", "sportsball123", "Ethan", "Reed", "player", "Redeemer Presbyterian", 21, "Home Run Organ Rally", False, True, "Redeemer Royals Featured Player"),
    ("player_thunder", "player.thunder@sportsball.local", "sportsball123", "Daniel", "Hayes", "player", "Redeemer Presbyterian", 4, "Lightning Fast Anthem", False, True, "Redeemer Thunder Featured Player"),
    ("player_covenant", "player.covenant@sportsball.local", "sportsball123", "Benjamin", "Price", "player", "Redeemer Presbyterian", 24, "Grace Upon Grace Organ Hook", False, True, "Redeemer Covenant Featured Player"),
    ("player_warriors", "player.warriors@sportsball.local", "sportsball123", "Sarah", "Collins", "player", "Hope Community Methodist", 15, "Grand Slam Anthem", False, True, "Hope Warriors Featured Player"),
    ("player_ironmen", "player.ironmen@sportsball.local", "sportsball123", "Gabriel", "Murphy", "player", "Hope Community Methodist", 10, "Touchdown Chimes", False, True, "Hope Ironmen Featured Player"),
    ("player_defenders", "player.defenders@sportsball.local", "sportsball123", "Jordan", "Bell", "player", "Hope Community Methodist", 22, "Goal Line Stand Theme", False, True, "Hope Defenders Featured Player"),

    # --- OFFICIALS & TESTING PERSONAS ---
    ("umpire_bob", "umpire.bob@sportsball.local", "sportsball123", "Bob", "Jenkins", "referee", "Grace Fellowship Church", None, "", False, True, "Certified Field Umpire & Referee"),
    ("free_agent_eli", "freeagent.eli@sportsball.local", "sportsball123", "Eli", "Walker", "player", "Grace Fellowship Church", 9, "", True, False, "Unassigned Free Agent Player"),
    ("free_agent_hannah", "freeagent.hannah@sportsball.local", "sportsball123", "Hannah", "Davis", "player", "Hope Community Methodist", 4, "", True, False, "Free Agent Waiting for Team Placement"),
    ("unverified_test", "unverified@sportsball.local", "sportsball123", "Tommy", "Test", "player", None, 18, "", False, False, "Unsigned Waiver Edge-Case Test"),
]


class Command(BaseCommand):
    help = "Creates pre-configured local test users with email logins for zero-friction testing"

    def add_arguments(self, parser):
        parser.add_argument(
            '--password',
            type=str,
            default='sportsball123',
            help='Universal password for all created test accounts (default: sportsball123)'
        )

    def handle(self, *args, **options):
        password = options['password']
        hashed_pw = make_password(password)
        churches_map = {c.name.lower(): c for c in Church.objects.all()}

        created_count = 0
        updated_count = 0

        self.stdout.write(self.style.NOTICE("Setting up local testing accounts with email logins..."))

        user_objects = {}
        for item in TEST_USERS:
            uname, email, _, fname, lname, role, ch_name, jersey, song_title, is_fa, waiver, desc = item
            church = churches_map.get(ch_name.lower()) if ch_name else None
            if not church and ch_name:
                for k, v in churches_map.items():
                    if ch_name.lower() in k or k in ch_name.lower():
                        church = v
                        break

            # Match on username or email, including legacy equivalents
            user = CustomUser.objects.filter(
                Q(username__iexact=uname) | Q(email__iexact=email)
            ).first()

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
            user.password = hashed_pw
            user.save()

            user_objects[uname] = user
            if created:
                created_count += 1
            else:
                updated_count += 1

        # Link Commissioners and Dues on partner churches
        grace_church = Church.objects.filter(name__icontains="Grace Fellowship").first()
        calvary_church = Church.objects.filter(name__icontains="Calvary Baptist").first()
        fire_dept = Church.objects.filter(name__icontains="Fire").first()
        redeemer_church = Church.objects.filter(name__icontains="Redeemer").first()
        hope_church = Church.objects.filter(name__icontains="Hope Community").first()

        if grace_church and user_objects.get("coach_sluggers"):
            grace_church.commissioner = user_objects.get("coach_sluggers")
            grace_church.dues_paid = True
            grace_church.save(update_fields=['commissioner', 'dues_paid'])

        if calvary_church and user_objects.get("coach_crusaders"):
            calvary_church.commissioner = user_objects.get("coach_crusaders")
            calvary_church.dues_paid = True
            calvary_church.save(update_fields=['commissioner', 'dues_paid'])

        if fire_dept and user_objects.get("coach_fire"):
            fire_dept.commissioner = user_objects.get("coach_fire")
            fire_dept.dues_paid = True
            fire_dept.save(update_fields=['commissioner', 'dues_paid'])

        if redeemer_church and user_objects.get("coach_royals"):
            redeemer_church.commissioner = user_objects.get("coach_royals")
            redeemer_church.dues_paid = True
            redeemer_church.save(update_fields=['commissioner', 'dues_paid'])

        if hope_church and user_objects.get("coach_warriors"):
            hope_church.commissioner = user_objects.get("coach_warriors")
            hope_church.dues_paid = True
            hope_church.save(update_fields=['commissioner', 'dues_paid'])

        # Auto-link featured players and coaches to teams if they exist
        team_links = [
            ("Grace Sluggers", "coach_sluggers", "player_sluggers"),
            ("Grace Overcomers", "coach_overcomers", "player_overcomers"),
            ("Grace Glory", "coach_glory", "player_glory"),
            ("Calvary Crusaders", "coach_crusaders", "player_crusaders"),
            ("Calvary Lions", "coach_lions", "player_lions"),
            ("Station 7 Smoke Eaters", "coach_fire", "player_fire"),
            ("Redeemer Royals", "coach_royals", "player_royals"),
            ("Redeemer Thunder", "coach_thunder", "player_thunder"),
            ("Redeemer Covenant", "coach_covenant", "player_covenant"),
            ("Hope Warriors", "coach_warriors", "player_warriors"),
            ("Hope Ironmen", "coach_ironmen", "player_ironmen"),
            ("Hope Defenders", "coach_defenders", "player_defenders"),
        ]

        for team_name, coach_key, player_key in team_links:
            team = Team.objects.filter(name__iexact=team_name).first()
            if not team:
                continue
            coach_user = user_objects.get(coach_key)
            player_user = user_objects.get(player_key)

            if coach_user:
                team.captain = coach_user
                team.save(update_fields=['captain'])
            if player_user and not team.players.filter(id=player_user.id).exists():
                team.players.add(player_user)
                SeasonRegistration.objects.update_or_create(
                    season=team.season,
                    player=player_user,
                    defaults={'preferred_team': team, 'status': 'approved', 'waiver_agreed': True}
                )

        self.stdout.write(self.style.SUCCESS(
            f"Done! {created_count} test users created, {updated_count} test users updated.\n"
            f"Universal Password: '{password}'\n\n"
            f"Ready-to-use Email Accounts:\n"
            f" • Overall Commish        : commissioner@sportsball.local\n"
            f" • Softball Commish       : commish.softball@sportsball.local\n"
            f" • Basketball Commish     : commish.basketball@sportsball.local\n"
            f" • Football Commish       : commish.football@sportsball.local\n"
            f" • 12 Coaches             : coach.<team_slug>@sportsball.local\n"
            f" • 12 Featured Players    : player.<team_slug>@sportsball.local\n"
        ))
