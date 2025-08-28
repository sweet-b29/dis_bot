from rest_framework import serializers
from .models import Player, PlayerBan

class PlayerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Player
        fields = ['id', 'discord_id', 'username', 'rank', 'wins', 'matches']

class PlayerBanSerializer(serializers.ModelSerializer):
    banned_by = serializers.PrimaryKeyRelatedField(read_only=True)
    class Meta:
        model = PlayerBan
        fields = ["id", "player", "reason", "expires_at", "banned_by", "created_at"]
        read_only_fields = ["banned_by", "created_at"]