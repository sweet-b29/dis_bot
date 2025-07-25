from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

# Create your models here.
class Player(models.Model):
    discord_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=255)
    rank = models.CharField(max_length=50, default='Unranked')
    wins = models.PositiveIntegerField(default=0)
    matches = models.PositiveIntegerField(default=0)
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
