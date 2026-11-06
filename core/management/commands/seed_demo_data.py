from datetime import date, timedelta
import io
import math
import struct
import wave
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Church, Announcement
from users.models import CustomUser
from leagues.models import League, Season, Team, SeasonRegistration, Game
from stats.models import StatCategory, PlayerGameStat, SPORT_DEFAULT_CATEGORIES


def _generate_demo_walkup_wav(freqs=(261.63, 329.63, 392.00, 523.25), duration_sec=6) -> bytes:
    """Generate a clean, cheerful ballpark organ chord fanfare WAV in memory for offline demo playback."""
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
    help = "Seeds demo data for Church Sports Leagues (churches, users, walk-up songs, leagues, seasons, teams, games, stats)"

    def handle(self, *args, **options):
        for sport, pairs in SPORT_DEFAULT_CATEGORIES.items():
            for name, abbr in pairs:
                StatCategory.objects.get_or_create(
                    sport=sport,
                    name=name,
                    defaults={'abbreviation': abbr}
                )

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
                'description': "Home of the Calvary Lions softball and basketball ministries.",
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
                'description': "Active young adult and family co-ed recreation teams.",
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
                'description': "Community outreach sports ministry welcoming players across the county.",
            }
        )

        # Seed Core Commissioner with standardized email
        admin_user = CustomUser.objects.filter(username="commissioner").first() or CustomUser.objects.filter(email="commissioner@sportsball.local").first()
        if not admin_user:
            admin_user = CustomUser(username="commissioner", email="commissioner@sportsball.local")
        admin_user.first_name = "Paul"
        admin_user.last_name = "Andrews"
        admin_user.email = "commissioner@sportsball.local"
        admin_user.role = 'admin'
        admin_user.church = grace
        admin_user.jersey_number = 99
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.waiver_signed = True
        admin_user.waiver_signature = "Paul Andrews"
        admin_user.walkup_song_title = "Ballpark Organ Charge Fanfare"
        admin_user.walkup_start_seconds = 0
        admin_user.walkup_duration_seconds = 5
        admin_user.set_password("sportsball123")
        admin_user.save()

        # Seed Coaches with intuitive email logins
        coaches_data = [
            ("coach_grace", "coach.grace@sportsball.local", "Caleb", "Brooks", grace, 34, "Victory Walk-Up Fanfare"),
            ("coach_calvary", "coach.calvary@sportsball.local", "David", "Miller", calvary, 23, "Eye of the Tiger (Organ Intro)"),
            ("coach_redeemer", "coach.redeemer@sportsball.local", "Luke", "Vance", redeemer, 11, "Chariots of Fire Theme"),
            ("coach_hope", "coach.hope@sportsball.local", "Sarah", "Jenkins", hope, 7, "Centerfield Clap Riff"),
        ]
        coaches = {}
        for uname, email, fname, lname, ch, jnum, song_title in coaches_data:
            u = CustomUser.objects.filter(username=uname).first() or CustomUser.objects.filter(email__iexact=email).first()
            if not u:
                u = CustomUser(username=uname, email=email)
            u.first_name = fname
            u.last_name = lname
            u.email = email
            u.role = 'coach'
            u.church = ch
            u.jersey_number = jnum
            u.waiver_signed = True
            u.waiver_signature = f"{fname} {lname}"
            u.walkup_song_title = song_title
            u.walkup_start_seconds = 0
            u.walkup_duration_seconds = 6
            u.set_password("sportsball123")
            if not u.walkup_song_file:
                wav_bytes = _generate_demo_walkup_wav(freqs=(293.66, 369.99, 440.00, 587.33), duration_sec=6)
                u.walkup_song_file.save(f"{uname}_walkup.wav", ContentFile(wav_bytes), save=False)
            u.save()
            coaches[uname] = u

        # Seed Players, Referees & Test Personas with email logins
        players_data = [
            ("player_josh", "player.josh@sportsball.local", "Josh", "Peterson", grace, 12, False, True, "Awesome God (Brass Riff)"),
            ("player_micah", "player.micah@sportsball.local", "Micah", "Thompson", calvary, 3, False, True, "Strike Up the Band"),
            ("player_ethan", "player.ethan@sportsball.local", "Ethan", "Reed", redeemer, 21, False, True, "Home Run Organ Rally"),
            ("player_sarah", "player.sarah@sportsball.local", "Sarah", "Collins", hope, 15, False, True, "Grand Slam Anthem"),
            ("umpire_bob", "umpire.bob@sportsball.local", "Bob", "Jenkins", grace, None, False, True, ""),
            ("free_agent_eli", "freeagent.eli@sportsball.local", "Eli", "Walker", grace, 9, True, False, ""),
            ("free_agent_hannah", "freeagent.hannah@sportsball.local", "Hannah", "Davis", hope, 4, True, False, ""),
            ("unverified_test", "unverified@sportsball.local", "Tommy", "Test", None, 18, False, False, ""),
        ]
        players = {}
        for uname, email, fname, lname, ch, jnum, is_fa, waiver, song_title in players_data:
            u = CustomUser.objects.filter(username=uname).first() or CustomUser.objects.filter(email__iexact=email).first()
            if not u:
                u = CustomUser(username=uname, email=email)
            u.first_name = fname
            u.last_name = lname
            u.email = email
            u.role = 'referee' if 'umpire' in uname else 'player'
            u.church = ch
            u.jersey_number = jnum
            u.is_free_agent = is_fa
            u.waiver_signed = waiver
            u.waiver_signature = f"{fname} {lname}" if waiver else ""
            u.bio = "Excited for fellowship and good sportsmanship this season!"
            u.walkup_song_title = song_title
            u.walkup_start_seconds = 0
            u.walkup_duration_seconds = 6
            u.set_password("sportsball123")
            if song_title and not u.walkup_song_file:
                wav_bytes = _generate_demo_walkup_wav(freqs=(261.63, 329.63, 392.00, 523.25), duration_sec=6)
                u.walkup_song_file.save(f"{uname}_walkup.wav", ContentFile(wav_bytes), save=False)
            u.save()
            players[uname] = u

        bball_league, _ = League.objects.get_or_create(
            name="Men's & Co-Ed Fellowship Basketball",
            defaults={
                'sport': 'basketball',
                'description': "5-on-5 full-court church basketball league with pre-game prayer and halftime devotionals.",
                'rules': "1. Two 20-minute running halves.\n2. Pre-game prayer at center court.\n3. Zero tolerance for technical fouls or unsportsmanlike conduct.",
                'admin': admin_user,
            }
        )
        softball_league, _ = League.objects.get_or_create(
            name="Spring/Summer Church Softball",
            defaults={
                'sport': 'softball',
                'description': "Slow-pitch co-ed church softball league played at Heritage Park fields with walk-up music and live GameCast.",
                'rules': "1. 7 innings or 60-minute time limit.\n2. ASA/USA approved bats only.\n3. Courtesy runners allowed twice per inning.",
                'admin': admin_user,
            }
        )

        today = date.today()
        bball_season, _ = Season.objects.get_or_create(
            league=bball_league,
            name="Fall/Winter 2026 Season",
            defaults={
                'start_date': today - timedelta(days=21),
                'end_date': today + timedelta(days=45),
                'current': True,
                'registration_open': True,
                'registration_fee': 35.00,
                'max_roster_size': 12,
            }
        )
        softball_season, _ = Season.objects.get_or_create(
            league=softball_league,
            name="Fall Ball Fellowship 2026",
            defaults={
                'start_date': today - timedelta(days=10),
                'end_date': today + timedelta(days=35),
                'current': True,
                'registration_open': True,
                'registration_fee': 30.00,
                'max_roster_size': 15,
            }
        )

        # Softball Teams + Live Dugout Console Demo Game
        sb_grace, _ = Team.objects.get_or_create(
            season=softball_season,
            name="Grace Sluggers",
            defaults={
                'league': softball_league,
                'church': grace,
                'captain': coaches['coach_grace'],
                'team_color': "Royal Blue",
                'dues_paid': True,
            }
        )
        sb_grace.captain = coaches['coach_grace']
        sb_grace.players.add(coaches['coach_grace'], players['player_josh'], admin_user)
        sb_grace.save(update_fields=['captain'])
        SeasonRegistration.objects.update_or_create(
            season=softball_season,
            player=players['player_josh'],
            defaults={'preferred_team': sb_grace, 'status': 'approved', 'waiver_agreed': True}
        )

        sb_calvary, _ = Team.objects.get_or_create(
            season=softball_season,
            name="Calvary Crusaders",
            defaults={
                'league': softball_league,
                'church': calvary,
                'captain': coaches['coach_calvary'],
                'team_color': "Crimson Red",
                'dues_paid': True,
            }
        )
        sb_calvary.captain = coaches['coach_calvary']
        sb_calvary.players.add(coaches['coach_calvary'], players['player_micah'])
        sb_calvary.save(update_fields=['captain'])
        SeasonRegistration.objects.update_or_create(
            season=softball_season,
            player=players['player_micah'],
            defaults={'preferred_team': sb_calvary, 'status': 'approved', 'waiver_agreed': True}
        )

        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        if not softball_season.games.exists():
            sb_game = Game.objects.create(
                season=softball_season,
                team1=sb_grace,
                team2=sb_calvary,
                date=now + timedelta(hours=2),
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

        # Run create_test_users to guarantee full sync and linking
        call_command('create_test_users')

        self.stdout.write(self.style.SUCCESS("Successfully seeded Church Sports Leagues & Walk-Up Dugout Console demo data with email logins!"))
