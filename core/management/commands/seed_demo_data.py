from datetime import date, timedelta
import io
import math
import struct
import wave
from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from core.models import Church
from users.models import CustomUser
from leagues.models import League, Season, Team, SeasonRegistration, Game
from stats.models import StatCategory, SPORT_DEFAULT_CATEGORIES


def _generate_demo_walkup_wav(freqs=(261.63, 329.63, 392.00, 523.25), duration_sec=6) -> bytes:
    """Generate a clean ballpark organ chord fanfare WAV in memory for offline demo playback."""
    sample_rate = 22050
    total_samples = int(sample_rate * duration_sec)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        note_len = max(1, total_samples // len(freqs))
        for i in range(total_samples):
            idx = min(len(freqs) - 1, i // note_len)
            f = freqs[idx]
            val = 0.45 * math.sin(2.0 * math.pi * f * (i / sample_rate)) + 0.25 * math.sin(2.0 * math.pi * (f * 1.5) * (i / sample_rate))
            sample = int(max(-32767, min(32767, val * 14000)))
            frames.extend(struct.pack('<h', sample))
        wf.writeframes(bytes(frames))
    return buf.getvalue()


class Command(BaseCommand):
    help = "Seeds demo data for Church Sports Leagues (5 orgs, 3 leagues, 12 teams, coaches, commissioners, 171 rostered players)"

    def handle(self, *args, **options):
        hashed_pw = make_password("sportsball123")
        cached_wav_bytes = _generate_demo_walkup_wav()

        # 1. Sport default stat categories
        for sport, pairs in SPORT_DEFAULT_CATEGORIES.items():
            for name, abbr in pairs:
                StatCategory.objects.get_or_create(
                    sport=sport,
                    name=name,
                    defaults={'abbreviation': abbr}
                )

        # 2. Churches & Outside Municipal Organizations
        grace, _ = Church.objects.get_or_create(
            name="Grace Fellowship Church",
            defaults={
                'denomination': "Non-Denominational",
                'address': "410 Oak Ridge Pkwy",
                'city': "Greenville",
                'state': "SC",
                'pastor_or_contact': "Pastor Mark Henderson",
                'contact_email': "sports@gracefellowship.org",
                'contact_phone': "555-210-4401",
                'description': "Host gym & ballfields for Tuesday and Thursday night softball and basketball fellowships.",
                'dues_paid': True,
            }
        )
        calvary, _ = Church.objects.get_or_create(
            name="Calvary Baptist Church",
            defaults={
                'denomination': "Baptist",
                'address': "880 Cedar Springs Rd",
                'city': "Greenville",
                'state': "SC",
                'pastor_or_contact': "Coach David Miller",
                'contact_email': "athletics@calvarybc.org",
                'contact_phone': "555-210-8820",
                'description': "Home of the Calvary Crusaders and Lions softball and sports ministries.",
                'dues_paid': True,
            }
        )
        fire_dept, _ = Church.objects.get_or_create(
            name="Greenville Fire & Rescue",
            defaults={
                'denomination': "First Responders / Municipal Partner",
                'address': "102 Firehouse Lane",
                'city': "Greenville",
                'state': "SC",
                'pastor_or_contact': "Chief Bill Henderson",
                'contact_email': "station7@greenvillefire.gov",
                'contact_phone': "555-911-0007",
                'description': "Greenville Fire & Rescue Department Station 7 Smoke Eaters - Outside Community Partner.",
                'dues_paid': True,
            }
        )
        redeemer, _ = Church.objects.get_or_create(
            name="Redeemer Presbyterian",
            defaults={
                'denomination': "Presbyterian (PCA)",
                'address': "125 Main Street",
                'city': "Greenville",
                'state': "SC",
                'pastor_or_contact': "Luke Vance",
                'contact_email': "lvance@redeemerpres.org",
                'contact_phone': "555-210-3390",
                'description': "Active fellowship with 3 competitive basketball teams.",
                'dues_paid': True,
            }
        )
        hope, _ = Church.objects.get_or_create(
            name="Hope Community Methodist",
            defaults={
                'denomination': "Methodist",
                'address': "520 Riverfront Ave",
                'city': "Greenville",
                'state': "SC",
                'pastor_or_contact': "Sarah Jenkins",
                'contact_email': "sjenkins@hopecommunity.org",
                'contact_phone': "555-210-7712",
                'description': "Community sports ministry hosting 3 co-ed flag football teams.",
                'dues_paid': True,
            }
        )

        # 3. Commissioners
        def _get_or_create_user(uname, email, fname, lname, role, church, is_staff, is_super, jersey=None, song_title=""):
            u = CustomUser.objects.filter(Q(username__iexact=uname) | Q(email__iexact=email)).first()
            if not u:
                u = CustomUser(username=uname, email=email)
            u.first_name = fname
            u.last_name = lname
            u.email = email
            u.role = role
            u.church = church
            u.jersey_number = jersey
            u.is_staff = is_staff
            u.is_superuser = is_super
            u.waiver_signed = True
            u.waiver_signature = f"{fname} {lname}"
            u.walkup_song_title = song_title
            u.walkup_start_seconds = 0
            u.walkup_duration_seconds = 6
            u.password = hashed_pw
            if song_title and not u.walkup_song_file:
                u.walkup_song_file.save(f"{uname}_walkup.wav", ContentFile(cached_wav_bytes), save=False)
            u.save()
            return u

        admin_user = _get_or_create_user(
            "commissioner", "commissioner@sportsball.local", "Paul", "Andrews", "admin", grace, True, True, 99, "Ballpark Organ Fanfare"
        )
        commish_softball = _get_or_create_user(
            "commish_softball", "commish.softball@sportsball.local", "Paul", "Henderson", "admin", grace, True, False, 90, "Softball Commission Fanfare"
        )
        commish_basketball = _get_or_create_user(
            "commish_basketball", "commish.basketball@sportsball.local", "Marcus", "Bradley", "admin", redeemer, True, False, 91, "Court Buzzer Fanfare"
        )
        commish_football = _get_or_create_user(
            "commish_football", "commish.football@sportsball.local", "Brian", "Taylor", "admin", hope, True, False, 92, "First Down Fanfare"
        )

        # 4. Leagues
        softball_league, _ = League.objects.get_or_create(
            name="Spring/Summer Church Softball",
            defaults={
                'sport': 'softball',
                'description': "Slow-pitch co-ed softball league played at Heritage Park ballfields with walk-up music and live GameCast.",
                'rules': "1. 7 innings or 60-minute time limit.\n2. 10 defensive players (min 8 to play).\n3. ASA/USA approved bats only.",
                'admin': commish_softball,
            }
        )
        softball_league.admin = commish_softball
        softball_league.save(update_fields=['admin'])

        bball_league, _ = League.objects.get_or_create(
            name="Men's & Co-Ed Fellowship Basketball",
            defaults={
                'sport': 'basketball',
                'description': "5-on-5 full-court church basketball league with pre-game prayer and halftime devotionals.",
                'rules': "1. Two 20-minute running halves.\n2. Pre-game prayer at center court.\n3. Zero tolerance for technical fouls.",
                'admin': commish_basketball,
            }
        )
        bball_league.admin = commish_basketball
        bball_league.save(update_fields=['admin'])

        football_league, _ = League.objects.get_or_create(
            name="Autumn Fellowship Flag Football",
            defaults={
                'sport': 'flag_football',
                'description': "7-on-7 non-contact co-ed flag football league emphasizing Christian sportsmanship and family fun.",
                'rules': "1. Two 25-minute halves.\n2. Screen blocking only, no intentional contact.\n3. Pre-game huddle prayer.",
                'admin': commish_football,
            }
        )
        football_league.admin = commish_football
        football_league.save(update_fields=['admin'])

        # 5. Seasons & Clean Demo State
        today = date.today()
        softball_season = Season.objects.filter(league=softball_league, name__icontains="2026").first()
        if not softball_season:
            softball_season = Season.objects.create(
                league=softball_league,
                name="Fall Ball Fellowship 2026",
                start_date=today - timedelta(days=10),
                end_date=today + timedelta(days=45),
                current=True,
                registration_open=True,
                registration_fee=30.00,
                max_roster_size=18,
            )
        else:
            softball_season.name = "Fall Ball Fellowship 2026"
            softball_season.current = True
            softball_season.save()
        Season.objects.filter(league=softball_league).exclude(id=softball_season.id).delete()
        softball_season.teams.exclude(name__in=[
            "Grace Sluggers", "Grace Overcomers", "Grace Glory",
            "Calvary Crusaders", "Calvary Lions", "Station 7 Smoke Eaters"
        ]).delete()

        bball_season = Season.objects.filter(league=bball_league, name__icontains="2026").first()
        if not bball_season:
            bball_season = Season.objects.create(
                league=bball_league,
                name="Fall/Winter 2026 Season",
                start_date=today - timedelta(days=14),
                end_date=today + timedelta(days=60),
                current=True,
                registration_open=True,
                registration_fee=35.00,
                max_roster_size=15,
            )
        else:
            bball_season.name = "Fall/Winter 2026 Season"
            bball_season.current = True
            bball_season.save()
        Season.objects.filter(league=bball_league).exclude(id=bball_season.id).delete()
        bball_season.teams.exclude(name__in=["Redeemer Royals", "Redeemer Thunder", "Redeemer Covenant"]).delete()

        football_season = Season.objects.filter(league=football_league, name__icontains="2026").first()
        if not football_season:
            football_season = Season.objects.create(
                league=football_league,
                name="Autumn Flag Football 2026",
                start_date=today - timedelta(days=7),
                end_date=today + timedelta(days=50),
                current=True,
                registration_open=True,
                registration_fee=35.00,
                max_roster_size=20,
            )
        else:
            football_season.name = "Autumn Flag Football 2026"
            football_season.current = True
            football_season.save()
        Season.objects.filter(league=football_league).exclude(id=football_season.id).delete()
        football_season.teams.exclude(name__in=[
            "Hope Warriors", "Hope Ironmen", "Hope Defenders"
        ]).delete()

        # 6. Team Specification Catalog
        # Exactly 15 for 6 softball teams (90 players), 11 for 3 bball teams (33 players), 16 for 3 football teams (48 players)
        TEAMS_CONFIG = [
            # --- SOFTBALL (6 TEAMS) ---
            {
                'key': 'grace_sluggers',
                'name': "Grace Sluggers",
                'league': softball_league,
                'season': softball_season,
                'church': grace,
                'color': "Royal Blue",
                'coach': ("coach_sluggers", "coach.sluggers@sportsball.local", "Caleb", "Brooks", 34, "Victory Walk-Up Fanfare"),
                'featured': ("player_sluggers", "player.sluggers@sportsball.local", "Josh", "Peterson", 12, "Awesome God (Brass Riff)"),
                'roster': [
                    ("Liam", "Foster", 2),
                    ("Noah", "Jenkins", 5),
                    ("Matthew", "Clark", 7),
                    ("Jacob", "Bell", 10),
                    ("Andrew", "Miller", 14),
                    ("Samuel", "Price", 17),
                    ("Nathan", "Young", 19),
                    ("Benjamin", "Ross", 22),
                    ("Daniel", "King", 25),
                    ("Christopher", "Wright", 28),
                    ("Ryan", "Turner", 31),
                    ("Jonathan", "Cooper", 33),
                    ("Zachary", "Ward", 37),
                    ("Tyler", "Morris", 42),
                ],  # 1 featured + 14 = 15 players
            },
            {
                'key': 'grace_overcomers',
                'name': "Grace Overcomers",
                'league': softball_league,
                'season': softball_season,
                'church': grace,
                'color': "Navy Blue",
                'coach': ("coach_overcomers", "coach.overcomers@sportsball.local", "Thomas", "Bradley", 45, "Ballpark Rally Theme"),
                'featured': ("player_overcomers", "player.overcomers@sportsball.local", "Luke", "Harper", 8, "Sweet Child O Mine Fanfare"),
                'roster': [
                    ("Jason", "Scott", 3),
                    ("Brandon", "Hill", 6),
                    ("Mason", "Green", 11),
                    ("Ethan", "Adams", 13),
                    ("Logan", "Baker", 16),
                    ("Lucas", "Gonzalez", 18),
                    ("Oliver", "Nelson", 20),
                    ("Elijah", "Carter", 24),
                    ("James", "Mitchell", 27),
                    ("Alexander", "Roberts", 29),
                    ("Henry", "Phillips", 35),
                    ("Jackson", "Campbell", 38),
                    ("Sebastian", "Parker", 41),
                    ("Owen", "Sanders", 44),
                ],  # 15 players
            },
            {
                'key': 'grace_glory',
                'name': "Grace Glory",
                'league': softball_league,
                'season': softball_season,
                'church': grace,
                'color': "Sky Blue",
                'coach': ("coach_glory", "coach.glory@sportsball.local", "Steven", "Vance", 50, "Glory Land Riff"),
                'featured': ("player_glory", "player.glory@sportsball.local", "Timothy", "Evans", 11, "Faithful Charge Theme"),
                'roster': [
                    ("Owen", "Edwards", 4),
                    ("William", "Collins", 9),
                    ("Henry", "Stewart", 14),
                    ("Leo", "Sanchez", 16),
                    ("Julian", "Morris", 21),
                    ("Charles", "Rogers", 23),
                    ("Christian", "Reed", 26),
                    ("Aaron", "Cook", 30),
                    ("Eli", "Morgan", 33),
                    ("Connor", "Bell", 36),
                    ("Caleb", "Murphy", 39),
                    ("Hunter", "Bailey", 44),
                    ("Isaac", "Rivera", 47),
                    ("Levi", "Brooks", 49),
                ],  # 15 players
            },
            {
                'key': 'calvary_crusaders',
                'name': "Calvary Crusaders",
                'league': softball_league,
                'season': softball_season,
                'church': calvary,
                'color': "Crimson Red",
                'coach': ("coach_crusaders", "coach.crusaders@sportsball.local", "David", "Miller", 23, "Eye of the Tiger (Intro)"),
                'featured': ("player_crusaders", "player.crusaders@sportsball.local", "Micah", "Thompson", 3, "Strike Up the Band"),
                'roster': [
                    ("Joshua", "Allen", 5),
                    ("Anthony", "Wright", 8),
                    ("Andrew", "Scott", 12),
                    ("Matthew", "Torres", 15),
                    ("Joseph", "Nguyen", 18),
                    ("David", "Hill", 20),
                    ("Gabriel", "Flores", 22),
                    ("Carter", "Green", 27),
                    ("Dylan", "Adams", 31),
                    ("Luke", "Baker", 34),
                    ("Jack", "Gonzalez", 38),
                    ("Levi", "Nelson", 40),
                    ("Julian", "Carter", 43),
                    ("Wyatt", "Perez", 46),
                ],  # 15 players
            },
            {
                'key': 'calvary_lions',
                'name': "Calvary Lions",
                'league': softball_league,
                'season': softball_season,
                'church': calvary,
                'color': "Gold & Maroon",
                'coach': ("coach_lions", "coach.lions@sportsball.local", "Robert", "Hayes", 32, "Lion Roar Fanfare"),
                'featured': ("player_lions", "player.lions@sportsball.local", "Aaron", "Cooper", 9, "Roar of the Lion"),
                'roster': [
                    ("Isaac", "Mitchell", 2),
                    ("Nathan", "Roberts", 6),
                    ("Samuel", "Phillips", 10),
                    ("Ryan", "Campbell", 13),
                    ("Christian", "Parker", 17),
                    ("Tyler", "Evans", 19),
                    ("Austin", "Edwards", 24),
                    ("Jordan", "Collins", 28),
                    ("Cameron", "Stewart", 31),
                    ("Justin", "Sanchez", 35),
                    ("Brandon", "Morris", 37),
                    ("Kevin", "Rogers", 41),
                    ("Adam", "Reed", 45),
                    ("Zach", "Watson", 48),
                ],  # 15 players
            },
            {
                'key': 'fire_smoke_eaters',
                'name': "Station 7 Smoke Eaters",
                'league': softball_league,
                'season': softball_season,
                'church': fire_dept,
                'color': "Firehouse Red",
                'coach': ("coach_fire", "coach.fire@sportsball.local", "Robert", "Briggs", 77, "Siren & Horn Fanfare"),
                'featured': ("player_fire", "player.fire@sportsball.local", "Jake", "Sullivan", 7, "Backdraft Stadium Anthem"),
                'roster': [
                    ("Travis", "Gallagher", 11),
                    ("Brett", "MacIntyre", 14),
                    ("Dustin", "O'Connor", 18),
                    ("Sean", "Callahan", 21),
                    ("Mike", "Donovan", 25),
                    ("Patrick", "Kelly", 29),
                    ("Rick", "Kowalski", 33),
                    ("Derek", "Hansen", 36),
                    ("Cole", "Martinez", 40),
                    ("Keith", "Vance", 44),
                    ("Shane", "Murphy", 48),
                    ("Kyle", "Dempsey", 52),
                    ("Connor", "Walsh", 55),
                    ("Brian", "O'Malley", 58),
                ],  # 15 players
            },

            # --- BASKETBALL (3 TEAMS UNDER REDEEMER PRESBYTERIAN) ---
            {
                'key': 'redeemer_royals',
                'name': "Redeemer Royals",
                'league': bball_league,
                'season': bball_season,
                'church': redeemer,
                'color': "Purple & White",
                'coach': ("coach_royals", "coach.royals@sportsball.local", "Luke", "Vance", 11, "Chariots of Fire Theme"),
                'featured': ("player_royals", "player.royals@sportsball.local", "Ethan", "Reed", 21, "Home Run Organ Rally"),
                'roster': [
                    ("Marcus", "Cole", 1),
                    ("Jordan", "White", 4),
                    ("Travis", "Gray", 7),
                    ("Tyler", "Stone", 13),
                    ("Eric", "Bennett", 15),
                    ("Kyle", "Harrison", 23),
                    ("Corey", "Brooks", 30),
                    ("Sean", "Howard", 33),
                    ("Derek", "Watson", 42),
                    ("Garrett", "Taylor", 50),
                ],  # 1 featured + 10 = 11 players
            },
            {
                'key': 'redeemer_thunder',
                'name': "Redeemer Thunder",
                'league': bball_league,
                'season': bball_season,
                'church': redeemer,
                'color': "Dark Teal",
                'coach': ("coach_thunder", "coach.thunder@sportsball.local", "Mark", "Davis", 30, "Thunderstruck Organ Hook"),
                'featured': ("player_thunder", "player.thunder@sportsball.local", "Daniel", "Hayes", 4, "Lightning Fast Anthem"),
                'roster': [
                    ("Justin", "Perry", 2),
                    ("Brett", "Long", 5),
                    ("Cody", "Russell", 9),
                    ("Craig", "Griffin", 12),
                    ("Trevor", "Hayes", 18),
                    ("Spencer", "Bryant", 22),
                    ("Wesley", "Alexander", 27),
                    ("Troy", "Butler", 35),
                    ("Colin", "Simmons", 44),
                    ("Dean", "Martin", 48),
                ],  # 11 players
            },
            {
                'key': 'redeemer_covenant',
                'name': "Redeemer Covenant",
                'league': bball_league,
                'season': bball_season,
                'church': redeemer,
                'color': "Emerald Green",
                'coach': ("coach_covenant", "coach.covenant@sportsball.local", "James", "Wilson", 15, "Covenant Victory Chime"),
                'featured': ("player_covenant", "player.covenant@sportsball.local", "Benjamin", "Price", 24, "Grace Upon Grace Organ Hook"),
                'roster': [
                    ("Bradley", "Foster", 3),
                    ("Garrett", "Powell", 6),
                    ("Russell", "Jenkins", 10),
                    ("Seth", "Patterson", 14),
                    ("Nolan", "Hughes", 20),
                    ("Mitchell", "Flores", 28),
                    ("Victor", "Washington", 32),
                    ("Grant", "Butler", 37),
                    ("Ross", "Simmons", 45),
                    ("Shane", "Cooper", 52),
                ],  # 11 players
            },

            # --- FLAG FOOTBALL (3 TEAMS UNDER HOPE COMMUNITY) ---
            {
                'key': 'hope_warriors',
                'name': "Hope Warriors",
                'league': football_league,
                'season': football_season,
                'church': hope,
                'color': "Forest Green",
                'coach': ("coach_warriors", "coach.warriors@sportsball.local", "Sarah", "Jenkins", 7, "Warrior Drum March"),
                'featured': ("player_warriors", "player.warriors@sportsball.local", "Sarah", "Collins", 15, "Grand Slam Anthem"),
                'roster': [
                    ("Rachel", "Adams", 2),
                    ("Jessica", "Campbell", 5),
                    ("Emily", "Davis", 8),
                    ("Megan", "Evans", 11),
                    ("Amanda", "Foster", 14),
                    ("Laura", "Garcia", 17),
                    ("Rebecca", "Harris", 20),
                    ("Hannah", "Jackson", 23),
                    ("Chloe", "Kelly", 26),
                    ("Grace", "Lewis", 29),
                    ("Olivia", "Martin", 32),
                    ("Emma", "Nelson", 35),
                    ("Sophia", "Owens", 38),
                    ("Ava", "Patterson", 41),
                    ("Mia", "Richardson", 44),
                ],  # 1 featured + 15 = 16 players
            },
            {
                'key': 'hope_ironmen',
                'name': "Hope Ironmen",
                'league': football_league,
                'season': football_season,
                'church': hope,
                'color': "Steel Gray",
                'coach': ("coach_ironmen", "coach.ironmen@sportsball.local", "Douglas", "Carter", 88, "Iron Sharpens Iron Fanfare"),
                'featured': ("player_ironmen", "player.ironmen@sportsball.local", "Gabriel", "Murphy", 10, "Touchdown Chimes"),
                'roster': [
                    ("Caleb", "Simmons", 3),
                    ("Lucas", "Bennett", 6),
                    ("Mason", "Griffin", 9),
                    ("Logan", "Russell", 13),
                    ("Jackson", "Bryant", 16),
                    ("Aiden", "Alexander", 19),
                    ("Elijah", "Butler", 24),
                    ("Oliver", "Barnes", 27),
                    ("Henry", "Ross", 30),
                    ("Samuel", "Henderson", 33),
                    ("Wyatt", "Coleman", 36),
                    ("Carter", "Jenkins", 40),
                    ("Owen", "Powell", 43),
                    ("Jayden", "Long", 47),
                    ("Eli", "Peterson", 51),
                ],  # 16 players
            },
            {
                'key': 'hope_defenders',
                'name': "Hope Defenders",
                'league': football_league,
                'season': football_season,
                'church': hope,
                'color': "Midnight Blue",
                'coach': ("coach_defenders", "coach.defenders@sportsball.local", "Anthony", "Woods", 54, "Fortress Defense March"),
                'featured': ("player_defenders", "player.defenders@sportsball.local", "Jordan", "Bell", 22, "Goal Line Stand Theme"),
                'roster': [
                    ("Zachary", "Fisher", 4),
                    ("Nathan", "Ellis", 8),
                    ("Isaac", "Harrison", 12),
                    ("Aaron", "Gibson", 15),
                    ("Christian", "McDonald", 18),
                    ("Hunter", "Cruz", 21),
                    ("Landon", "Marshall", 25),
                    ("Adrian", "Ortiz", 28),
                    ("Julian", "Gomez", 31),
                    ("Dominic", "Murray", 34),
                    ("Nolan", "Freeman", 37),
                    ("Xavier", "Wells", 42),
                    ("Ian", "Webb", 45),
                    ("Adam", "Simpson", 49),
                    ("Sean", "Dixon", 53),
                ],  # 16 players
            },
        ]

        teams_map = {}

        for cfg in TEAMS_CONFIG:
            # Create / link Coach
            c_uname, c_email, c_fname, c_lname, c_num, c_song = cfg['coach']
            coach_user = _get_or_create_user(
                c_uname, c_email, c_fname, c_lname, "coach", cfg['church'], False, False, c_num, c_song
            )

            team, _ = Team.objects.get_or_create(
                season=cfg['season'],
                name=cfg['name'],
                defaults={
                    'league': cfg['league'],
                    'church': cfg['church'],
                    'captain': coach_user,
                    'team_color': cfg['color'],
                    'dues_paid': True,
                }
            )
            team.captain = coach_user
            team.save(update_fields=['captain'])

            # Collect team players
            team_players = [coach_user]

            # Featured Player
            f_uname, f_email, f_fname, f_lname, f_num, f_song = cfg['featured']
            featured_user = _get_or_create_user(
                f_uname, f_email, f_fname, f_lname, "player", cfg['church'], False, False, f_num, f_song
            )
            team_players.append(featured_user)

            # Roster Players
            for idx, (p_fname, p_lname, p_num) in enumerate(cfg['roster'], start=1):
                p_uname = f"p_{cfg['key']}_{idx}"
                p_email = f"{p_fname.lower()}.{p_lname.lower()}@{cfg['key']}.sportsball.local"
                p_user = _get_or_create_user(
                    p_uname, p_email, p_fname, p_lname, "player", cfg['church'], False, False, p_num
                )
                team_players.append(p_user)

            # Ensure roster has exact requested count
            # Note: For team.players count, we include featured + roster players.
            # Roster list alone is 14 (softball), 10 (bball), 15 (football).
            # Adding featured_user gives exactly: 15 (softball), 11 (bball), 16 (football).
            roster_only = [featured_user] + [
                CustomUser.objects.filter(email=f"{p_fname.lower()}.{p_lname.lower()}@{cfg['key']}.sportsball.local").first()
                for p_fname, p_lname, _ in cfg['roster']
            ]
            team.players.set(roster_only)

            # Ensure registrations
            for p in roster_only:
                SeasonRegistration.objects.update_or_create(
                    season=cfg['season'],
                    player=p,
                    defaults={'preferred_team': team, 'status': 'approved', 'waiver_agreed': True}
                )

            teams_map[cfg['key']] = team

        # 7. Scheduled & Live Games
        now = timezone.now().replace(minute=0, second=0, microsecond=0)

        # Softball Games
        sb_grace = teams_map['grace_sluggers']
        sb_calvary = teams_map['calvary_crusaders']
        sb_overcomers = teams_map['grace_overcomers']
        sb_lions = teams_map['calvary_lions']
        sb_glory = teams_map['grace_glory']
        sb_fire = teams_map['fire_smoke_eaters']

        if not softball_season.games.exists():
            sb_game = Game.objects.create(
                season=softball_season,
                team1=sb_grace,
                team2=sb_calvary,
                date=now + timedelta(hours=1),
                location="Heritage Park - Diamond #1",
                status='in_progress',
                game_type='regular',
                week_number=1,
                team1_score=3,
                team2_score=2,
                team1_hits=5,
                team2_hits=4,
                current_inning=3,
                inning_half='bottom',
                outs=1,
                runner_on_first=True,
                runner_on_second=False,
                runner_on_third=True,
            )
            sb_game.ensure_lineups_initialized()
            sb_game.advance_to_next_batter()
            sb_game.log_play("Grace Sluggers rally in the bottom of the 3rd with runners on the corners!")
            sb_game.save()

            Game.objects.create(
                season=softball_season,
                team1=sb_overcomers,
                team2=sb_lions,
                date=now + timedelta(days=2, hours=18),
                location="Heritage Park - Diamond #2",
                status='scheduled',
                game_type='regular',
                week_number=1,
            )
            Game.objects.create(
                season=softball_season,
                team1=sb_glory,
                team2=sb_fire,
                date=now + timedelta(days=4, hours=19),
                location="Heritage Park - Diamond #1",
                status='scheduled',
                game_type='regular',
                week_number=1,
            )

        # Basketball Games
        if not bball_season.games.exists():
            Game.objects.create(
                season=bball_season,
                team1=teams_map['redeemer_royals'],
                team2=teams_map['redeemer_thunder'],
                date=now + timedelta(days=1, hours=19),
                location="Redeemer Family Life Center",
                status='scheduled',
                game_type='regular',
                week_number=1,
            )
            Game.objects.create(
                season=bball_season,
                team1=teams_map['redeemer_thunder'],
                team2=teams_map['redeemer_covenant'],
                date=now + timedelta(days=3, hours=20),
                location="Redeemer Family Life Center",
                status='scheduled',
                game_type='regular',
                week_number=1,
            )

        # Flag Football Games
        if not football_season.games.exists():
            Game.objects.create(
                season=football_season,
                team1=teams_map['hope_warriors'],
                team2=teams_map['hope_ironmen'],
                date=now + timedelta(days=2, hours=10),
                location="Riverfront Park - Field A",
                status='scheduled',
                game_type='regular',
                week_number=1,
            )
            Game.objects.create(
                season=football_season,
                team1=teams_map['hope_ironmen'],
                team2=teams_map['hope_defenders'],
                date=now + timedelta(days=5, hours=11),
                location="Riverfront Park - Field B",
                status='scheduled',
                game_type='regular',
                week_number=1,
            )

        # 8. Seed Voice Packs & Soundboard Effects
        call_command('seed_voice_packs')

        # 9. Run create_test_users to guarantee full sync and linking
        call_command('create_test_users')

        self.stdout.write(self.style.SUCCESS(
            "Successfully seeded Church Sports Leagues!\n"
            " • 5 Organizations (Grace Fellowship, Calvary Baptist, Station 7 Fire Dept, Redeemer Presbyterian, Hope Community)\n"
            " • 3 Leagues & Seasons (Softball, Basketball, Flag Football)\n"
            " • 12 Teams seeded with coaches and complete rosters:\n"
            "   - 6 Softball Teams (15 players each = 90 players)\n"
            "   - 3 Basketball Teams (11 players each = 33 players)\n"
            "   - 3 Flag Football Teams (16 players each = 48 players)\n"
            " • Total rostered players: 171\n"
            " • 4 Commissioners (Overall, Softball, Basketball, Football)\n"
            " • 12 Coaches & 12 Featured Players ready for demo logins with 'sportsball123'!"
        ))
