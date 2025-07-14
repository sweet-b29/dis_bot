from rest_framework import serializers
from .models import Match

class MatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Match
        fields = '__all__'

class SetWinnerSerializer(serializers.Serializer):
    winner_team = serializers.ChoiceField(choices=[1, 2])