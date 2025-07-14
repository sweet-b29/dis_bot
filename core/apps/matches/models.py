from django.db import models
from apps.players.models import Player

class Match(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    captain_1 = models.ForeignKey(Player, related_name='matches_as_captain1', on_delete=models.CASCADE)
    captain_2 = models.ForeignKey(Player, related_name='matches_as_captain2', on_delete=models.CASCADE)
    team_1 = models.ManyToManyField(Player, related_name='matches_in_team1', blank=True)
    team_2 = models.ManyToManyField(Player, related_name='matches_in_team2', blank=True)
    winner_team = models.PositiveSmallIntegerField(
        choices=[(1, 'Team 1'), (2, 'Team 2')],
        null=True,
        blank=True
    )
    map_name = models.CharField(max_length=50, null=True, blank=True, verbose_name="Карта матча")
    sides = models.JSONField(null=True, blank=True, verbose_name="Стороны команд (атака/защита)")

    def __str__(self):
        return f"Матч {self.id}: {self.captain_1.username} vs {self.captain_2.username}"