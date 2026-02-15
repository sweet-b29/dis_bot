from django.db import models
from django.conf import settings
from apps.players.models import Player

class Match(models.Model):
    class Mode(models.TextChoices):
        M2 = "2x2", "2x2"
        M3 = "3x3", "3x3"
        M4 = "4x4", "4x4"
        M5 = "5x5", "5x5"

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    captain_1 = models.ForeignKey(Player, related_name='matches_as_captain1', on_delete=models.CASCADE)
    captain_2 = models.ForeignKey(Player, related_name='matches_as_captain2', on_delete=models.CASCADE)
    team_1 = models.ManyToManyField(Player, related_name='matches_in_team1', blank=True)
    team_2 = models.ManyToManyField(Player, related_name='matches_in_team2', blank=True)

    # NEW
    mode = models.CharField(
        max_length=3,
        choices=Mode.choices,
        default=Mode.M5,
        db_index=True,
        verbose_name="Режим лобби",
    )
    lobby_name = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Название лобби",
    )

    winner_team = models.PositiveSmallIntegerField(choices=[(1, 'Team 1'), (2, 'Team 2')], null=True, blank=True)
    map_name = models.CharField(max_length=50, null=True, blank=True, verbose_name="Карта матча")
    sides = models.JSONField(null=True, blank=True, verbose_name="Стороны команд (атака/защита)")

    def __str__(self):
        return f"Матч {self.id}: {self.captain_1.username} vs {self.captain_2.username}"

class MatchEvent(models.Model):
    match = models.ForeignKey("Match", on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    data = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="match_events",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.type} (match={self.match_id})"
