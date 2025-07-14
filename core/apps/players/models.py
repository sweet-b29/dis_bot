from django.db import models
from django.contrib.auth.models import User

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