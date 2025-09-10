import logging
from django.db import transaction
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Match, MatchEvent
from .serializers import MatchSerializer, SetWinnerSerializer

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

    def perform_create(self, serializer):
        match = serializer.save()
        actor = self.request.user if self.request.user.is_authenticated else None
        log_match_event(match, MatchEvent.Type.CREATED, actor=actor, map=match.map_name)

    @action(detail=True, methods=['post'])
    def set_winner(self, request, pk=None):
        match = self.get_object()
        if match.winner_team is not None:
            return Response({"detail": "Winner already set"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            winner = int(request.data.get("winner_team"))
        except (TypeError, ValueError):
            return Response({"detail": "winner_team must be 1 or 2"}, status=status.HTTP_400_BAD_REQUEST)
        if winner not in (1, 2):
            return Response({"detail": "winner_team must be 1 or 2"}, status=status.HTTP_400_BAD_REQUEST)

            # составы
        team1_ids = set(match.team_1.values_list("id", flat=True))
        team2_ids = set(match.team_2.values_list("id", flat=True))
        if not team1_ids or not team2_ids:
            return Response({"detail": "Both teams must have players"}, status=status.HTTP_400_BAD_REQUEST)

        winners_ids = team1_ids if winner == 1 else team2_ids
        losers_ids = team2_ids if winner == 1 else team1_ids

        # дубли: если игрок попал в обе команды, убираем его из проигравших
        duplicates = winners_ids & losers_ids
        if duplicates:
            logger.warning(f"Match {match.id}: players present in both teams: {sorted(list(duplicates))}")
            losers_ids -= duplicates

        with transaction.atomic():
            match.winner_team = winner
            match.save(update_fields=["winner_team"])

            Player = match.team_1.model  # модель игроков
            if winners_ids:
                Player.objects.filter(id__in=winners_ids).update(
                    wins=F("wins") + 1,
                    matches=F("matches") + 1,
                )
            if losers_ids:
                Player.objects.filter(id__in=losers_ids).update(
                    matches=F("matches") + 1,
                )

        # журнал события (если MatchEvent есть)
        try:
            from .models import MatchEvent
            MatchEvent.objects.create(match=match, type="win_set", data={"winner_team": winner})
        except Exception:
            pass

        return Response({"status": "ok"}, status=status.HTTP_200_OK)