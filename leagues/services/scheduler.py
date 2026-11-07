import datetime
from typing import List, Dict, Any, Tuple, Set
from django.utils import timezone
from django.db import transaction
from leagues.models import Season, Game, Team


WEEKDAY_MAP = {
    '0': 0, 'mon': 0, 'monday': 0,
    '1': 1, 'tue': 1, 'tuesday': 1,
    '2': 2, 'wed': 2, 'wednesday': 2,
    '3': 3, 'thu': 3, 'thursday': 3,
    '4': 4, 'fri': 4, 'friday': 4,
    '5': 5, 'sat': 5, 'saturday': 5,
    '6': 6, 'sun': 6, 'sunday': 6,
}


def parse_time_str(time_str: str) -> datetime.time:
    """Parse time string like '18:30', '6:30 PM', '09:00', '19:45'."""
    s = time_str.strip()
    for fmt in ('%H:%M', '%I:%M %p', '%I:%M%p', '%H:%M:%S'):
        try:
            return datetime.datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    return datetime.time(18, 30)


class ScheduleGeneratorService:
    def __init__(
        self,
        season: Season,
        start_date: datetime.date,
        game_days: List[int],
        time_slots: List[datetime.time],
        venues: List[str],
        blackout_dates: Set[datetime.date] = None,
        protect_wednesdays: bool = True,
        protect_sunday_mornings: bool = True,
        double_round_robin: bool = False,
        add_weather_buffer: bool = True,
    ):
        self.season = season
        self.start_date = start_date
        self.game_days = sorted(list(set(game_days))) if game_days else [1, 3]  # Default Tue, Thu
        self.time_slots = sorted(list(set(time_slots))) if time_slots else [datetime.time(18, 30)]
        self.venues = [v.strip() for v in venues if v.strip()] or ["Main Gym / Field 1"]
        self.blackout_dates = blackout_dates or set()
        self.protect_wednesdays = protect_wednesdays
        self.protect_sunday_mornings = protect_sunday_mornings
        self.double_round_robin = double_round_robin
        self.add_weather_buffer = add_weather_buffer

    def generate_round_robin_pairings(self, teams: List[Team]) -> List[List[Tuple[Team, Team]]]:
        """Generate balanced home/away round robin pairings using circle method."""
        rotation = list(teams)
        if len(rotation) % 2 == 1:
            rotation.append(None)  # Bye week

        n = len(rotation)
        num_rounds = n - 1
        half = n // 2

        rounds_matchups = []
        for r in range(num_rounds):
            week_pairs = []
            for i in range(half):
                t1 = rotation[i]
                t2 = rotation[n - 1 - i]
                if t1 is not None and t2 is not None:
                    # Alternate home/away each round
                    if r % 2 == 1 and i == 0:
                        week_pairs.append((t2, t1))
                    else:
                        week_pairs.append((t1, t2))
            rounds_matchups.append(week_pairs)
            rotation = [rotation[0]] + [rotation[-1]] + rotation[1:-1]

        if self.double_round_robin:
            second_half = [[(t2, t1) for (t1, t2) in week] for week in rounds_matchups]
            rounds_matchups.extend(second_half)

        return rounds_matchups

    def get_week_slots(self, week_base_monday: datetime.date) -> List[Tuple[datetime.datetime, str]]:
        """
        Generate chronological (datetime, venue) slots for a given calendar week,
        honoring blackout dates, Wednesday service protections, and Sunday morning protections.
        """
        slots = []
        # Check all days of that week (Monday to Sunday)
        for offset in range(7):
            cur_date = week_base_monday + datetime.timedelta(days=offset)
            weekday = cur_date.weekday()

            if weekday not in self.game_days:
                continue

            if cur_date in self.blackout_dates:
                continue

            for t in self.time_slots:
                # Wednesday evening protection (typically services start 6:00/6:30 PM)
                if self.protect_wednesdays and weekday == 2 and t >= datetime.time(17, 0):
                    continue

                # Sunday morning protection (Sunday worship services)
                if self.protect_sunday_mornings and weekday == 6 and t < datetime.time(13, 0):
                    continue

                for v in self.venues:
                    dt = datetime.datetime.combine(cur_date, t)
                    slots.append((timezone.make_aware(dt) if timezone.is_naive(dt) else dt, v))

        return sorted(slots, key=lambda s: (s[0], s[1]))

    def plan_schedule(self) -> List[Dict[str, Any]]:
        """
        Produce a list of planned game dictionaries without writing to the database.
        Each entry has: week_number, team1, team2, date, location, notes.
        """
        teams = list(self.season.teams.all())
        if len(teams) < 2:
            return []

        rounds_matchups = self.generate_round_robin_pairings(teams)

        # Find the Monday corresponding to start_date
        monday_offset = self.start_date.weekday()
        week_monday = self.start_date - datetime.timedelta(days=monday_offset)

        planned_games = []
        week_idx = 1

        for matchups in rounds_matchups:
            # Advance to find a week that has available slots
            slots = []
            while not slots:
                slots = self.get_week_slots(week_monday)
                if not slots:
                    week_monday += datetime.timedelta(days=7)

            # Assign matchups to slots
            for slot_idx, (home, away) in enumerate(matchups):
                # Cycle or advance slots if more matchups than slots in week
                cur_slot = slots[slot_idx % len(slots)]
                # If slot_idx >= len(slots), add hours to prevent collision
                extra_hours = (slot_idx // len(slots)) * 2
                game_dt = cur_slot[0] + datetime.timedelta(hours=extra_hours)
                venue = cur_slot[1]

                planned_games.append({
                    'week_number': week_idx,
                    'team1': home,
                    'team2': away,
                    'date': game_dt,
                    'location': venue,
                    'notes': f"Week {week_idx} Matchup",
                })

            week_idx += 1
            week_monday += datetime.timedelta(days=7)

        return planned_games

    @transaction.atomic
    def execute_and_save(self, clear_existing_scheduled: bool = True) -> int:
        """
        Executes the planning algorithm and commits newly scheduled games into the database.
        """
        if clear_existing_scheduled:
            self.season.games.filter(status='scheduled', game_type='regular').delete()

        planned = self.plan_schedule()
        games_to_create = []
        for p in planned:
            games_to_create.append(
                Game(
                    season=self.season,
                    team1=p['team1'],
                    team2=p['team2'],
                    date=p['date'],
                    location=p['location'],
                    game_type='regular',
                    status='scheduled',
                    week_number=p['week_number'],
                    notes=p['notes'],
                )
            )

        if games_to_create:
            Game.objects.bulk_create(games_to_create)

        # Save configuration to season
        self.season.has_weather_buffer_week = self.add_weather_buffer
        self.season.schedule_config = {
            'game_days': self.game_days,
            'time_slots': [t.strftime('%H:%M') for t in self.time_slots],
            'venues': self.venues,
            'protect_wednesdays': self.protect_wednesdays,
            'protect_sunday_mornings': self.protect_sunday_mornings,
            'double_round_robin': self.double_round_robin,
        }
        self.season.save(update_fields=['has_weather_buffer_week', 'schedule_config'])

        return len(games_to_create)
