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
        serializer = SetWinnerSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # ИДЕМПОТЕНТНОСТЬ: если победитель уже установлен — запрещаем повтор
        if match.winner_team is not None:
            return Response({"detail": "Winner already set"}, status=status.HTTP_400_BAD_REQUEST)

        winner = serializer.validated_data['winner_team']
        winners_qs = match.team_1.all() if winner == 1 else match.team_2.all()
        losers_qs  = match.team_2.all() if winner == 1 else match.team_1.all()

        with transaction.atomic():
            match.winner_team = winner
            match.save(update_fields=["winner_team"])

            # Обновляем статистику игроков один раз
            for p in winners_qs.select_for_update():
                p.wins += 1
                p.matches += 1
                p.save(update_fields=["wins", "matches"])

            for p in losers_qs.select_for_update():
                p.matches += 1
                p.save(update_fields=["matches"])

        actor = request.user if request.user.is_authenticated else None
        log_match_event(match, MatchEvent.Type.WIN_SET, actor=actor, winner_team=winner)
        return Response({'status': 'updated'}, status=status.HTTP_200_OK)
