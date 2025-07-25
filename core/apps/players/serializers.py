from rest_framework import serializers
from .models import Player, PlayerBan

class PlayerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Player
        fields = ['id', 'discord_id', 'username', 'rank', 'wins', 'matches']

class PlayerBanSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlayerBan
        fields = '__all__'