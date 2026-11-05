from datetime import date, timedelta
import io
import math
import struct
import wave
from django.core.files.base import ContentFile
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

        admin_user, created = CustomUser.objects.get_or_create(
            username="commissioner",
            defaults={
                'first_name': "Paul",
                'last_name': "Andrews",
                'email': "commissioner@churchleagues.org",
                'role': 'admin',
                'church': grace,
                'jersey_number': 99,
                'is_staff': True,
                'is_superuser': True,
                'waiver_signed': True,
                'walkup_song_title': "Ballpark Organ Charge Fanfare",
                'walkup_start_seconds': 0,
                'walkup_duration_seconds': 5,
            }
        )
        if created:
            admin_user.set_password("league1234")
            admin_user.save()

        coaches_data = [
            ("coach_david", "David", "Miller", calvary, 23, "Eye of the Tiger (Organ Intro)"),
            ("coach_luke", "Luke", "Vance", redeemer, 11, "Chariots of Fire Theme"),
            ("coach_sarah", "Sarah", "Jenkins", hope, 7, "Centerfield Clap Riff"),
            ("coach_caleb", "Caleb", "Brooks", grace, 34, "Victory Walk-Up Fanfare"),
        ]
        coaches = []
        for uname, fname, lname, ch, jnum, song_title in coaches_data:
            u, c = CustomUser.objects.get_or_create(
                username=uname,
                defaults={
                    'first_name': fname,
                    'last_name': lname,
                    'email': f"{uname}@example.org",
                    'role': 'coach',
                    'church': ch,
                    'jersey_number': jnum,
                    'waiver_signed': True,
                    'walkup_song_title': song_title,
                    'walkup_start_seconds': 0,
                    'walkup_duration_seconds': 6,
                }
            )
            if c:
                u.set_password("league1234")
            if not u.walkup_song_file:
                wav_bytes = _generate_demo_walkup_wav(freqs=(293.66, 369.99, 440.00, 587.33), duration_sec=6)
                u.walkup_song_file.save(f"{uname}_walkup.wav", ContentFile(wav_bytes), save=False)
            u.save()
            coaches.append(u)

        players_data = [
            ("josh_p", "Josh", "Peterson", grace, 12, False, "Awesome God (Brass Riff)"),
            ("micah_t", "Micah", "Thompson", calvary, 3, False, "Strike Up the Band"),
            ("ethan_r", "Ethan", "Reed", redeemer, 21, False, "Home Run Organ Rally"),
            ("noah_w", "Noah", "Williams", hope, 15, False, "Grand Slam Anthem"),
            ("eli_free", "Eli", "Walker", grace, 9, True, ""),
            ("hannah_free", "Hannah", "Collins", hope, 4, True, ""),
        ]
        players = []
        for uname, fname, lname, ch, jnum, is_fa, song_title in players_data:
            u, c = CustomUser.objects.get_or_create(
                username=uname,
                defaults={
                    'first_name': fname,
                    'last_name': lname,
                    'email': f"{uname}@example.org",
                    'role': 'player',
                    'church': ch,
                    'jersey_number': jnum,
                    'is_free_agent': is_fa,
                    'waiver_signed': not is_fa,
                    'bio': "Excited for fellowship and good games this season!",
                    'walkup_song_title': song_title,
                    'walkup_start_seconds': 0,
                    'walkup_duration_seconds': 6,
                }
            )
            if c:
                u.set_password("league1234")
            if song_title and not u.walkup_song_file:
                wav_bytes = _generate_demo_walkup_wav(freqs=(261.63, 329.63, 392.00, 523.25), duration_sec=6)
                u.walkup_song_file.save(f"{uname}_walkup.wav", ContentFile(wav_bytes), save=False)
            u.save()
            players.append(u)

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
                'captain': coaches[3],
                'team_color': "Royal Blue",
                'dues_paid': True,
            }
        )
        sb_grace.players.add(coaches[3], players[0], admin_user)

        sb_calvary, _ = Team.objects.get_or_create(
            season=softball_season,
            name="Calvary Crusaders",
            defaults={
                'league': softball_league,
                'church': calvary,
                'captain': coaches[0],
                'team_color': "Crimson Red",
                'dues_paid': True,
            }
        )
        sb_calvary.players.add(coaches[0], players[1])

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

        self.stdout.write(self.style.SUCCESS("Successfully seeded Church Sports Leagues & Walk-Up Dugout Console demo data!"))
