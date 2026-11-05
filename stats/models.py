from django.db import models
from django.conf import settings


SPORT_DEFAULT_CATEGORIES = {
    'basketball': [
        ('Points', 'PTS'),
        ('Rebounds', 'REB'),
        ('Assists', 'AST'),
        ('Steals', 'STL'),
        ('Blocks', 'BLK'),
        ('Three-Pointers Made', '3PM'),
    ],
    'softball': [
        ('Hits', 'H'),
        ('Home Runs', 'HR'),
        ('Runs Batted In', 'RBI'),
        ('Runs Scored', 'R'),
        ('Strikeouts (Pitcher)', 'K'),
    ],
    'volleyball': [
        ('Kills', 'K'),
        ('Service Aces', 'ACE'),
        ('Digs', 'DIG'),
        ('Blocks', 'BLK'),
        ('Assists', 'AST'),
    ],
    'flag_football': [
        ('Touchdowns', 'TD'),
        ('Passing Touchdowns', 'PTD'),
        ('Interceptions', 'INT'),
        ('Flag Pulls / Sacks', 'FLG'),
    ],
    'soccer': [
        ('Goals', 'G'),
        ('Assists', 'A'),
        ('Saves', 'SV'),
    ],
    'pickleball': [
        ('Points Won', 'PTS'),
        ('Aces', 'ACE'),
        ('Winners', 'WIN'),
    ],
    'cornhole': [
        ('Bag-In-The-Hole (Cornholes)', '4B'),
        ('Total Points', 'PTS'),
    ],
    'other': [
        ('Points', 'PTS'),
        ('Assists', 'AST'),
    ],
}


class StatCategory(models.Model):
    sport = models.CharField(max_length=30, default='basketball')
    name = models.CharField(max_length=80)
    abbreviation = models.CharField(max_length=15)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name_plural = "Stat Categories"
        unique_together = [('sport', 'name')]
        ordering = ['sport', 'name']

    def __str__(self):
        return f"{self.name} ({self.abbreviation}) [{self.sport}]"


class PlayerGameStat(models.Model):
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='game_stats'
    )
    game = models.ForeignKey(
        'leagues.Game',
        on_delete=models.CASCADE,
        related_name='player_stats'
    )
    team = models.ForeignKey(
        'leagues.Team',
        on_delete=models.CASCADE,
        related_name='player_stats',
        null=True,
        blank=True
    )
    category = models.CharField(max_length=50)
    value = models.IntegerField(default=0)

    class Meta:
        unique_together = [('player', 'game', 'category')]
        ordering = ['-value', 'player__username']

    def __str__(self):
        return f"{self.player.username} - {self.category}: {self.value} ({self.game})"
