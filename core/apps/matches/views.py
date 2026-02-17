import logging
from rest_framework import viewsets
from .models import Match, MatchEvent
from .serializers import MatchSerializer, SetWinnerSerializer
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.db.models import F

logger = logging.getLogger(__name__)

def log_match_event(match: Match, event_type: str, actor=None, **data):
    """Безопасная запись события в журнал (ошибка не ломает основной поток)."""
    try:
        MatchEvent.objects.create(match=match, type=event_type, actor=actor, data=data or {})
    except Exception:
        logger.exception("Failed to write MatchEvent")

class MatchViewSet(viewsets.ModelViewSet):
    queryset = Match.objects.all().order_by('-created_at')
    serializer_class = MatchSerializer

    def create(self, request, *args, **kwargs):
        external_id = request.data.get("external_id")
        if external_id:
            existing = Match.objects.filter(external_id=external_id).first()
            if existing:
                ser = self.get_serializer(existing)
                return Response(ser.data, status=status.HTTP_200_OK)

        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        match = serializer.save()

        if match.captain_1_id:
            match.team_1.add(match.captain_1_id)
        if match.captain_2_id:
            match.team_2.add(match.captain_2_id)

        actor = self.request.user if self.request.user.is_authenticated else None
        log_match_event(match, MatchEvent.Type.CREATED, actor=actor, map=match.map_name)

    @action(detail=True, methods=['post'])
    @action(detail=True, methods=["post"])
    def set_winner(self, request, pk=None):
        match = self.get_object()

        # уже установлен победитель — запрещаем повтор
        if match.winner_team is not None:
            return Response({"detail": "Winner already set"}, status=status.HTTP_400_BAD_REQUEST)

        # валидируем тело запроса (winner_team: 1 или 2)
        ser = SetWinnerSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        winner = ser.validated_data["winner_team"]

        # составы команд
        team1_ids = set(match.team_1.values_list("id", flat=True))
        team2_ids = set(match.team_2.values_list("id", flat=True))

        # капитаны тоже считаются участниками (на случай если их не добавляют в M2M)
        if getattr(match, "captain_1_id", None):
            team1_ids.add(match.captain_1_id)
        if getattr(match, "captain_2_id", None):
            team2_ids.add(match.captain_2_id)

        if not team1_ids or not team2_ids:
            return Response({"detail": "Both teams must have players"}, status=status.HTTP_400_BAD_REQUEST)

        winners_ids = team1_ids if winner == 1 else team2_ids
        losers_ids = team2_ids if winner == 1 else team1_ids

        # если игрок оказался в обеих командах — выкидываем из проигравших
        duplicates = winners_ids & losers_ids
        if duplicates:
            logger.warning(f"Match {match.id}: players present in both teams: {sorted(list(duplicates))}")
            losers_ids -= duplicates

        with transaction.atomic():
            match.winner_team = winner
            match.save(update_fields=["winner_team"])

            # ✅ стата/лидерборд ТОЛЬКО для 5x5
            if match.mode == "5x5":
                Player = match.team_1.model

                if winners_ids:
                    Player.objects.filter(id__in=winners_ids).update(
                        wins=F("wins") + 1,
                        matches=F("matches") + 1,
                    )
                if losers_ids:
                    Player.objects.filter(id__in=losers_ids).update(
                        matches=F("matches") + 1,
                    )

            # лог события (используй твой safe-хелпер)
            actor = request.user if request.user.is_authenticated else None
            log_match_event(match, "win_set", actor=actor, winner_team=winner)

        return Response({"status": "ok"}, status=status.HTTP_200_OK)