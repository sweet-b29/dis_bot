from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

# Create your models here.
class Player(models.Model):
    discord_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=255)
    rank = models.CharField(max_length=50, default='Unranked')
    wins = models.PositiveIntegerField(default=0, db_index=True)
    matches = models.PositiveIntegerField(default=0, db_index=True)
    last_name_change = models.DateTimeField(null=True, blank=True)
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.username} ({self.rank})"


class PlayerBan(models.Model):
    player = models.ForeignKey("Player", on_delete=models.CASCADE, related_name="bans")
    reason = models.TextField()
    banned_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def is_active(self):
        return self.expires_at > timezone.now()

    def __str__(self):
        return f"{self.player} — banned until {self.expires_at.strftime('%Y-%m-%d %H:%M')}"


class Season(models.Model):
    name = models.CharField(max_length=64, unique=True)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class PlayerSeasonStat(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="stats")
    discord_id = models.BigIntegerField(db_index=True)

    username = models.CharField(max_length=32)
    rank = models.CharField(max_length=32, default="Unranked")

    wins = models.PositiveIntegerField(default=0)
    matches = models.PositiveIntegerField(default=0)

    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("season", "discord_id")
        indexes = [
            models.Index(fields=["season", "wins"]),
            models.Index(fields=["season", "matches"]),
        ]

    def __str__(self) -> str:
        return f"{self.season.name} | {self.username} ({self.discord_id})"