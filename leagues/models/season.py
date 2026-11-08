"""Season domain model defining competition windows, schedules, standings, and official budgets."""
from __future__ import annotations
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Sum


class Season(models.Model):
    league = models.ForeignKey('League', on_delete=models.CASCADE, related_name='seasons')
    name = models.CharField(max_length=100)
    start_date = models.DateField(db_index=True)
    end_date = models.DateField()
    current = models.BooleanField(default=False)
    registration_open = models.BooleanField(default=True)
    registration_fee = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    max_roster_size = models.PositiveIntegerField(default=15)
    discord_webhook_url = models.URLField(
        blank=True,
        help_text="Discord Webhook URL for this specific season"
    )
    venmo_handle = models.CharField(
        max_length=60,
        blank=True,
        help_text="Venmo username for dues (e.g. @GraceChurchSports)"
    )
    cashapp_handle = models.CharField(
        max_length=60,
        blank=True,
        help_text="CashApp handle for dues (e.g. $GraceLeague)"
    )
    paypal_link = models.URLField(
        blank=True,
        help_text="Direct PayPal.me link (e.g. https://paypal.me/gracechurch)"
    )
    has_weather_buffer_week = models.BooleanField(
        default=True,
        help_text="Reserve a buffer week at end of regular season for rainout makeups"
    )
    schedule_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Saved schedule preferences (days, times, venues, blackouts)"
    )
    officials_budget = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0.00,
        help_text="Total budget allocated for paid officials ($)"
    )
    official_default_pay = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=30.00,
        help_text="Default pay per official per game ($)"
    )
    officials_pool = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='officiating_seasons',
        help_text="Approved referees, umpires, and scorekeepers for this season"
    )

    def get_officials_budget_summary(self):
        from decimal import Decimal
        from leagues.models.official import GameOfficialAssignment
        from django.db.models import Sum
        assignments = GameOfficialAssignment.objects.filter(game__season=self)
        total_allocated = Decimal(str(assignments.aggregate(Sum('pay_amount'))['pay_amount__sum'] or '0.00'))
        total_paid = Decimal(str(assignments.filter(pay_status='paid').aggregate(Sum('pay_amount'))['pay_amount__sum'] or '0.00'))
        budget = Decimal(str(self.officials_budget or '0.00'))
        remaining = budget - total_allocated
        total_owed = total_allocated - total_paid
        return {
            'budget': float(budget),
            'total_allocated': float(total_allocated),
            'allocated': float(total_allocated),
            'total_paid': float(total_paid),
            'paid': float(total_paid),
            'total_owed': float(total_owed),
            'owed': float(total_owed),
            'remaining': float(remaining),
            'total_assignments': assignments.count(),
            'needs_sub_count': assignments.filter(status='declined').count(),
        }

    class Meta:
        ordering = ['-current', '-start_date']

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("Season end date cannot be earlier than start date.")

    def get_standings(self):
        """
        Calculate and return ordered standings for all teams in this season.
        Returns a list of dicts with:
          team, played, wins, losses, ties, win_pct, points_for, points_against, point_diff, streak
        """
        teams = list(self.teams.select_related('church', 'captain').all())
        stats_map = {
            team.id: {
                'team': team,
                'played': 0,
                'wins': 0,
                'losses': 0,
                'ties': 0,
                'win_pct': 0.0,
                'points_for': 0,
                'points_against': 0,
                'point_diff': 0,
                'results': [],
            }
            for team in teams
        }

        completed_games = self.games.filter(
            status='completed',
            game_type='regular'
        ).order_by('date', 'id')

        for game in completed_games:
            t1_id = game.team1_id
            t2_id = game.team2_id
            s1 = game.team1_score or 0
            s2 = game.team2_score or 0

            if t1_id in stats_map:
                st1 = stats_map[t1_id]
                st1['played'] += 1
                st1['points_for'] += s1
                st1['points_against'] += s2
                if s1 > s2:
                    st1['wins'] += 1
                    st1['results'].append('W')
                elif s1 < s2:
                    st1['losses'] += 1
                    st1['results'].append('L')
                else:
                    st1['ties'] += 1
                    st1['results'].append('T')

            if t2_id in stats_map:
                st2 = stats_map[t2_id]
                st2['played'] += 1
                st2['points_for'] += s2
                st2['points_against'] += s1
                if s2 > s1:
                    st2['wins'] += 1
                    st2['results'].append('W')
                elif s2 < s1:
                    st2['losses'] += 1
                    st2['results'].append('L')
                else:
                    st2['ties'] += 1
                    st2['results'].append('T')

        standings = []
        for entry in stats_map.values():
            played = entry['played']
            if played > 0:
                entry['win_pct'] = round((entry['wins'] + 0.5 * entry['ties']) / played, 3)
            entry['point_diff'] = entry['points_for'] - entry['points_against']

            results = entry['results']
            if not results:
                entry['streak'] = '-'
            else:
                last = results[-1]
                count = 0
                for r in reversed(results):
                    if r == last:
                        count += 1
                    else:
                        break
                entry['streak'] = f"{last}{count}"
            standings.append(entry)

        standings.sort(
            key=lambda x: (x['win_pct'], x['wins'], x['point_diff'], x['points_for'], x['team'].name),
            reverse=True
        )
        for idx, row in enumerate(standings, start=1):
            row['rank'] = idx
        return standings

    def __str__(self):
        return f"{self.league.name} - {self.name}"


