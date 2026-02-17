from __future__ import annotations

import uuid
from django.db import models
from django.conf import settings
from apps.players.models import Player


class Match(models.Model):
    class Mode(models.TextChoices):
        M2 = "2x2", "2x2"
        M3 = "3x3", "3x3"
        M4 = "4x4", "4x4"
        M5 = "5x5", "5x5"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        FINISHED = "finished", "Finished"
        ABANDONED = "abandoned", "Abandoned"
        CANCELED = "canceled", "Canceled"

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата завершения")

    #ИДЕМПОТЕНТНОСТЬ (защита от дублей)
    external_id = models.UUIDField(
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        verbose_name="External id (bot)",
    )

    #Идентификатор лобби
    lobby_id = models.PositiveIntegerField(null=True, blank=True, db_index=True, verbose_name="Lobby ID")
    lobby_name = models.CharField(max_length=64, null=True, blank=True, db_index=True, verbose_name="Название лобби")

    mode = models.CharField(
        max_length=3,
        choices=Mode.choices,
        default=Mode.M5,
        db_index=True,
        verbose_name="Режим лобби",
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name="Статус матча",
    )

    captain_1 = models.ForeignKey(Player, related_name="matches_as_captain1", on_delete=models.CASCADE)
    captain_2 = models.ForeignKey(Player, related_name="matches_as_captain2", on_delete=models.CASCADE)
    team_1 = models.ManyToManyField(Player, related_name="matches_in_team1", blank=True)
    team_2 = models.ManyToManyField(Player, related_name="matches_in_team2", blank=True)

    winner_team = models.PositiveSmallIntegerField(
        choices=[(1, "Team 1"), (2, "Team 2")],
        null=True,
        blank=True,
        verbose_name="Победитель",
    )

    map_name = models.CharField(max_length=50, null=True, blank=True, verbose_name="Карта матча")
    sides = models.JSONField(null=True, blank=True, verbose_name="Стороны команд (атака/защита)")

    duration_seconds = models.PositiveIntegerField(null=True, blank=True, verbose_name="Длительность (сек)")
    score_team1 = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Счёт Team 1")
    score_team2 = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Счёт Team 2")
    region = models.CharField(max_length=32, null=True, blank=True, verbose_name="Регион/сервер")
    overtime = models.BooleanField(default=False, verbose_name="Овертайм")
    forfeit = models.BooleanField(default=False, verbose_name="Форфит")
    forfeit_reason = models.CharField(max_length=128, null=True, blank=True, verbose_name="Причина форфита")

    def __str__(self):
        return f"Match {self.id} ({self.mode}) {self.captain_1_id} vs {self.captain_2_id}"


class MatchEvent(models.Model):
    class Type(models.TextChoices):
        CREATED = "created", "Created"
        WIN_SET = "win_set", "Win Set"
        STATUS_CHANGED = "status_changed", "Status Changed"

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=64, choices=Type.choices)
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
