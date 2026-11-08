"""Team and SeasonRegistration models managing church rosters, dues, invites, and registration."""
from __future__ import annotations
import secrets
from django.db import models
from django.conf import settings
from django.urls import reverse


class Team(models.Model):
    name = models.CharField(max_length=100)
    league = models.ForeignKey('League', on_delete=models.CASCADE, related_name='teams')
    season = models.ForeignKey('Season', on_delete=models.CASCADE, related_name='teams')
    church = models.ForeignKey(
        'core.Church',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='teams',
        help_text="Sponsoring or home church"
    )
    captain = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='captained_teams',
        limit_choices_to={'role__in': ['admin', 'coach', 'player']}
    )
    players = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='teams',
        blank=True
    )
    team_color = models.CharField(max_length=50, blank=True, default='Navy Blue')
    dues_paid = models.BooleanField(default=False, help_text="Has team registration fee been paid?")
    default_lineup = models.JSONField(
        default=dict,
        blank=True,
        help_text="Saved default lineup template (batting order and positions)"
    )
    invite_code = models.CharField(
        max_length=32,
        unique=True,
        blank=True,
        null=True,
        db_index=True,
        help_text="Unique 1-tap player invite code"
    )
    intro_track = models.ForeignKey(
        'users.AudioTrack',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='teams_using_as_intro',
        help_text="Official team walk-on / intro anthem across all sports"
    )

    class Meta:
        ordering = ['name']
        unique_together = [('season', 'name')]

    def save(self, *args, **kwargs):
        if not self.invite_code:
            import secrets
            self.invite_code = secrets.token_urlsafe(8)
        if self.season_id and not self.league_id:
            self.league = self.season.league
        super().save(*args, **kwargs)

    def get_invite_url(self, request=None):
        from django.urls import reverse
        if not self.invite_code:
            import secrets
            self.invite_code = secrets.token_urlsafe(8)
            self.save(update_fields=['invite_code'])
        path = reverse('join_team_invite', kwargs={'invite_code': self.invite_code})
        if request:
            return request.build_absolute_uri(path)
        return path

    def get_active_intro(self) -> dict:
        """
        Returns active team intro anthem dictionary:
        {'title': str, 'url': str, 'start': float, 'duration': float, 'is_vetoed': bool, 'veto_reason': str}
        """
        if self.intro_track:
            track = self.intro_track
            if track.is_vetoed:
                if track.replacement_track and not track.replacement_track.is_vetoed:
                    url, start, dur = track.replacement_track.get_effective_playback()
                    return {
                        'title': track.replacement_track.title,
                        'url': url,
                        'start': start,
                        'duration': dur,
                        'is_vetoed': False,
                        'veto_reason': '',
                    }
                return {
                    'title': track.title,
                    'url': '',
                    'start': 0.0,
                    'duration': 0.0,
                    'is_vetoed': True,
                    'veto_reason': track.veto_reason,
                }
            url, start, dur = track.get_effective_playback()
            return {
                'title': track.title,
                'url': url,
                'start': start,
                'duration': dur,
                'is_vetoed': False,
                'veto_reason': '',
            }
        return {
            'title': '',
            'url': '',
            'start': 0.0,
            'duration': 0.0,
            'is_vetoed': False,
            'veto_reason': '',
        }

    def __str__(self):
        return f"{self.name} ({self.season.name})"

    def get_sportsmanship_summary(self):
        """Calculates aggregate sportsmanship metrics and renewal standing."""
        ratings = list(self.received_sportsmanship_ratings.all())
        good_th = float(self.league.sportsmanship_good_threshold) if (self.league and self.league.sportsmanship_good_threshold) else 4.0
        rev_th = float(self.league.sportsmanship_review_threshold) if (self.league and self.league.sportsmanship_review_threshold) else 3.0

        if not ratings:
            return {
                'count': 0,
                'avg_score': 5.0,
                'avg_respect': 5.0,
                'avg_bench': 5.0,
                'status': 'good',
                'status_label': 'Good Standing (Unrated)',
                'good_threshold': good_th,
                'review_threshold': rev_th,
            }

        avg_score = round(sum(r.score for r in ratings) / len(ratings), 2)
        avg_respect = round(sum(r.respect_for_officials for r in ratings) / len(ratings), 2)
        avg_bench = round(sum(r.bench_conduct for r in ratings) / len(ratings), 2)

        if avg_score >= good_th:
            status = 'good'
            status_label = 'Good Standing (Auto-Renew)'
        elif avg_score >= rev_th:
            status = 'review'
            status_label = 'Pastoral / Committee Review Required'
        else:
            status = 'probation'
            status_label = 'Probation / Deny Renewal'

        return {
            'count': len(ratings),
            'avg_score': avg_score,
            'avg_respect': avg_respect,
            'avg_bench': avg_bench,
            'status': status,
            'status_label': status_label,
            'good_threshold': good_th,
            'review_threshold': rev_th,
        }




class SeasonRegistration(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Assignment / Approval'),
        ('approved', 'Approved / Rostered'),
        ('declined', 'Declined'),
    ]

    season = models.ForeignKey('Season', on_delete=models.CASCADE, related_name='registrations')
    player = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='season_registrations')
    preferred_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registration_requests',
        help_text="Leave blank to register as a Free Agent"
    )
    is_free_agent = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    waiver_agreed = models.BooleanField(default=False)
    dues_paid = models.BooleanField(default=False)
    notes = models.CharField(max_length=255, blank=True, help_text="Skill level, position preference, or availability notes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('season', 'player')]
        ordering = ['-created_at']

    def get_active_intro(self) -> dict:
        """
        Returns active team intro anthem dictionary:
        {'title': str, 'url': str, 'start': float, 'duration': float, 'is_vetoed': bool, 'veto_reason': str}
        """
        if self.intro_track:
            track = self.intro_track
            if track.is_vetoed:
                if track.replacement_track and not track.replacement_track.is_vetoed:
                    url, start, dur = track.replacement_track.get_effective_playback()
                    return {
                        'title': track.replacement_track.title,
                        'url': url,
                        'start': start,
                        'duration': dur,
                        'is_vetoed': False,
                        'veto_reason': '',
                    }
                return {
                    'title': track.title,
                    'url': '',
                    'start': 0.0,
                    'duration': 0.0,
                    'is_vetoed': True,
                    'veto_reason': track.veto_reason,
                }
            url, start, dur = track.get_effective_playback()
            return {
                'title': track.title,
                'url': url,
                'start': start,
                'duration': dur,
                'is_vetoed': False,
                'veto_reason': '',
            }
        return {
            'title': '',
            'url': '',
            'start': 0.0,
            'duration': 0.0,
            'is_vetoed': False,
            'veto_reason': '',
        }

    def __str__(self):
        target = self.preferred_team.name if self.preferred_team else "Free Agent"
        return f"{self.player.username} -> {self.season.name} ({target})"


