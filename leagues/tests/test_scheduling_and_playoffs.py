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



class TestSchedulingAndPlayoffsCase(BaseLeagueTestCase):

    def test_standings_calculation(self):
        Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now(),
            location="Gym A",
            status='completed',
            game_type='regular',
            team1_score=60,
            team2_score=50,
        )
        standings = self.season.get_standings()
        self.assertEqual(standings[0]['team'], self.team1)
        self.assertEqual(standings[0]['wins'], 1)
        self.assertEqual(standings[0]['point_diff'], 10)
        self.assertEqual(standings[0]['streak'], 'W1')

        team2_row = [r for r in standings if r['team'] == self.team2][0]
        self.assertEqual(team2_row['losses'], 1)
        self.assertEqual(team2_row['point_diff'], -10)
        self.assertEqual(team2_row['streak'], 'L1')


    def test_round_robin_schedule_generator(self):
        self.client.login(username="admin_user", password="password123")
        start_dt = (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT18:30')
        resp = self.client.post(reverse('generate_schedule', args=[self.season.id]), {
            'start_datetime': start_dt,
            'location': 'Fellowship Court 1',
            'double_round_robin': False,
            'clear_existing_scheduled': True,
        })
        self.assertEqual(resp.status_code, 302)
        # 4 teams in single round-robin = 6 games across 3 weeks
        self.assertEqual(self.season.games.filter(game_type='regular').count(), 6)


    def test_playoff_bracket_generation_and_advancement(self):
        self.client.login(username="admin_user", password="password123")
        resp = self.client.post(reverse('generate_playoffs', args=[self.season.id]))
        self.assertEqual(resp.status_code, 302)
        semis = list(self.season.games.filter(game_type='playoff_sf').order_by('id'))
        self.assertEqual(len(semis), 2)

        # Complete both semifinals
        semis[0].team1_score = 70
        semis[0].team2_score = 60
        semis[0].status = 'completed'
        semis[0].save()

        semis[1].team1_score = 55
        semis[1].team2_score = 62
        semis[1].status = 'completed'
        semis[1].save()

        resp_adv = self.client.post(reverse('advance_playoffs_to_final', args=[self.season.id]))
        self.assertEqual(resp_adv.status_code, 302)
        final_game = self.season.games.filter(game_type='playoff_final').first()
        self.assertIsNotNone(final_game)
        self.assertEqual(final_game.team1, semis[0].team1)
        self.assertEqual(final_game.team2, semis[1].team2)


    def test_create_game_restricted_to_league_commissioner(self):
        # coach_user is not league commissioner -> blocked
        self.client.login(username="coach_user", password="password123")
        resp_coach = self.client.post(reverse('create_game', args=[self.season.id]), {
            'team1': self.team1.id,
            'team2': self.team2.id,
            'date': (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT18:30'),
            'location': 'Gym A',
            'game_type': 'regular',
            'week_number': 1,
            'status': 'scheduled',
        })
        self.assertEqual(resp_coach.status_code, 302)
        self.assertFalse(Game.objects.filter(location='Gym A', week_number=1).exists())

        # admin_user is league commissioner -> succeeds
        self.client.login(username="admin_user", password="password123")
        resp_admin = self.client.post(reverse('create_game', args=[self.season.id]), {
            'team1': self.team1.id,
            'team2': self.team2.id,
            'date': (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT18:30'),
            'location': 'Gym A',
            'game_type': 'regular',
            'week_number': 1,
            'status': 'scheduled',
        })
        self.assertEqual(resp_admin.status_code, 302)
        self.assertTrue(Game.objects.filter(location='Gym A', week_number=1).exists())


    def test_smart_multi_slot_schedule_generation(self):
        self.client.login(username="admin_user", password="password123")
        tomorrow = timezone.localdate() + timedelta(days=1)

        # 1. Test preview mode (no DB writes)
        resp_preview = self.client.post(reverse('generate_schedule', args=[self.season.id]), {
            'action': 'preview',
            'start_date': tomorrow.strftime('%Y-%m-%d'),
            'game_days': ['1', '3'],
            'time_slots': '18:30, 19:45',
            'venues': 'Court 1\nCourt 2',
            'protect_wednesdays': True,
            'protect_sunday_mornings': True,
            'double_round_robin': False,
            'add_weather_buffer': True,
            'clear_existing_scheduled': True,
        })
        self.assertEqual(resp_preview.status_code, 200)
        self.assertIsNotNone(resp_preview.context['preview_games'])
        self.assertEqual(len(resp_preview.context['preview_games']), 6)
        self.assertEqual(self.season.games.filter(game_type='regular').count(), 0)

        # 2. Test generate mode (commits to DB)
        resp_generate = self.client.post(reverse('generate_schedule', args=[self.season.id]), {
            'action': 'generate',
            'start_date': tomorrow.strftime('%Y-%m-%d'),
            'game_days': ['1', '3'],
            'time_slots': '18:30, 19:45',
            'venues': 'Court 1\nCourt 2',
            'protect_wednesdays': True,
            'protect_sunday_mornings': True,
            'double_round_robin': False,
            'add_weather_buffer': True,
            'clear_existing_scheduled': True,
        })
        self.assertEqual(resp_generate.status_code, 302)
        self.assertEqual(self.season.games.filter(game_type='regular').count(), 6)

        self.season.refresh_from_db()
        self.assertTrue(self.season.has_weather_buffer_week)
        self.assertIn('game_days', self.season.schedule_config)
        self.assertEqual(self.season.schedule_config['game_days'], [1, 3])


    def test_ics_calendar_feed_export(self):
        # Create a sample game
        game_dt = timezone.now() + timedelta(days=3)
        game = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=game_dt,
            location="Gym Court 1",
            status="scheduled",
            game_type="regular"
        )

        # 1. Team calendar feed
        resp_team = self.client.get(reverse('team_calendar_ics', args=[self.team1.id]))
        self.assertEqual(resp_team.status_code, 200)
        self.assertIn('text/calendar', resp_team['Content-Type'])
        content_str = resp_team.content.decode('utf-8')
        self.assertIn('BEGIN:VCALENDAR', content_str)
        self.assertIn('BEGIN:VEVENT', content_str)
        self.assertIn('Gym Court 1', content_str)
        self.assertIn(f'{self.team1.name} vs {self.team2.name}', content_str)

        # 2. Season calendar feed
        resp_season = self.client.get(reverse('season_calendar_ics', args=[self.season.id]))
        self.assertEqual(resp_season.status_code, 200)
        self.assertIn('text/calendar', resp_season['Content-Type'])
        self.assertIn('BEGIN:VCALENDAR', resp_season.content.decode('utf-8'))

        # 3. User calendar feed (anonymous forbidden)
        resp_anon = self.client.get(reverse('user_calendar_ics'))
        self.assertEqual(resp_anon.status_code, 403)

        # User calendar feed (authenticated player)
        self.team1.players.add(self.player_user)
        self.client.login(username="player_user", password="password123")
        resp_user = self.client.get(reverse('user_calendar_ics'))
        self.assertEqual(resp_user.status_code, 200)
        self.assertIn('text/calendar', resp_user['Content-Type'])
        self.assertIn(self.team1.name, resp_user.content.decode('utf-8'))


    def test_schedule_grid_and_swap_game_slots(self):
        g1 = Game.objects.create(
            season=self.season,
            team1=self.team1,
            team2=self.team2,
            date=timezone.now() + timedelta(days=2),
            location="Court 1",
            status="scheduled",
            game_type="regular",
            week_number=1
        )
        g2 = Game.objects.create(
            season=self.season,
            team1=self.team3,
            team2=self.team4,
            date=timezone.now() + timedelta(days=5),
            location="Court 2",
            status="scheduled",
            game_type="regular",
            week_number=2
        )

        # Schedule grid view
        resp_grid = self.client.get(reverse('schedule_grid', args=[self.season.id]))
        self.assertEqual(resp_grid.status_code, 200)
        self.assertContains(resp_grid, "Court 1")
        self.assertContains(resp_grid, "Court 2")

        # Non-commissioner slot swap forbidden/redirected
        self.client.login(username="player_user", password="password123")
        self.client.post(reverse('swap_game_slots', args=[self.season.id]), {
            'game1_id': g1.id,
            'game2_id': g2.id,
        })
        g1.refresh_from_db()
        self.assertEqual(g1.location, "Court 1")

        # Commissioner swaps slots
        self.client.login(username="admin_user", password="password123")
        resp_swap = self.client.post(reverse('swap_game_slots', args=[self.season.id]), {
            'game1_id': g1.id,
            'game2_id': g2.id,
        })
        self.assertEqual(resp_swap.status_code, 302)

        g1.refresh_from_db()
        g2.refresh_from_db()
        self.assertEqual(g1.location, "Court 2")
        self.assertEqual(g2.location, "Court 1")
        self.assertEqual(g1.week_number, 2)
        self.assertEqual(g2.week_number, 1)


    def test_field_double_booking_validation(self):
        from leagues.forms import GameForm
        game_time = timezone.now() + timedelta(days=5)
        Game.objects.create(
            season=self.season, team1=self.team1, team2=self.team2,
            date=game_time, location="Heritage Field 1", status='scheduled'
        )

        # Attempt to schedule another game 30 minutes later at same field
        local_clash_time = timezone.localtime(game_time) + timedelta(minutes=30)
        clashing_form = GameForm(data={
            'team1': self.team1.id,
            'team2': self.team2.id,
            'date': local_clash_time.strftime('%Y-%m-%dT%H:%M'),
            'location': 'Heritage Field 1',
            'game_type': 'regular',
            'status': 'scheduled',
            'week_number': 2,
        }, season=self.season)

        self.assertFalse(clashing_form.is_valid())
        self.assertIn("Venue Conflict", str(clashing_form.errors))


