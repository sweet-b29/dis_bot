from rest_framework import serializers

from .models import Match


class MatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Match
        fields = [
            "id",
            "created_at",
            "finished_at",

            "external_id",
            "external_match_key",

            "discord_guild_id",
            "discord_channel_id",
            "discord_message_id",
            "win_message_id",

            "lobby_id",
            "lobby_name",
            "mode",
            "is_ranked",
            "status",

            "captain_1",
            "captain_2",
            "team_1",
            "team_2",
            "winner_team",

            "map_name",
            "sides",

            "duration_seconds",
            "score_team1",
            "score_team2",
            "region",
            "overtime",
            "forfeit",
            "forfeit_reason",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "finished_at",
            "status",
            "winner_team",
        ]

    def validate(self, attrs):
        captain_1 = attrs.get("captain_1") or getattr(self.instance, "captain_1", None)
        captain_2 = attrs.get("captain_2") or getattr(self.instance, "captain_2", None)

        if captain_1 and captain_2 and captain_1 == captain_2:
            raise serializers.ValidationError(
                {"captain_2": "captain_1 and captain_2 must be different."}
            )

        team_1 = attrs.get("team_1")
        team_2 = attrs.get("team_2")

        if self.instance:
            if team_1 is None:
                team_1 = list(self.instance.team_1.all())
            if team_2 is None:
                team_2 = list(self.instance.team_2.all())

        team_1 = set(team_1 or [])
        team_2 = set(team_2 or [])

        duplicates = team_1 & team_2
        if duplicates:
            raise serializers.ValidationError(
                "Player cannot be in both team_1 and team_2."
            )

        return attrs


class SetWinnerSerializer(serializers.Serializer):
    winner_team = serializers.ChoiceField(choices=[1, 2])