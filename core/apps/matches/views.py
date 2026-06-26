import logging

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Match, MatchEvent
from .serializers import MatchSerializer, SetWinnerSerializer

logger = logging.getLogger(__name__)


def log_match_event(match: Match, event_type: str, actor=None, **data):
    try:
        MatchEvent.objects.create(
            match=match,
            type=event_type,
            actor=actor,
            data=data or {},
        )
    except Exception:
        logger.exception("Failed to write MatchEvent")


class MatchViewSet(viewsets.ModelViewSet):
    serializer_class = MatchSerializer
    permission_classes = [IsAuthenticated]

    queryset = (
        Match.objects
        .select_related("captain_1", "captain_2")
        .prefetch_related("team_1", "team_2", "events")
        .all()
        .order_by("-created_at")
    )

    def create(self, request, *args, **kwargs):
        """
        Идемпотентное создание матча.

        Если бот повторно отправит create_match с тем же external_id
        или external_match_key, мы не создаём дубль, а возвращаем уже
        существующий матч.
        """
        external_id = request.data.get("external_id")
        external_match_key = request.data.get("external_match_key")

        existing = None

        if external_id:
            existing = Match.objects.filter(external_id=external_id).first()

        if not existing and external_match_key:
            existing = Match.objects.filter(external_match_key=external_match_key).first()

        if existing:
            serializer = self.get_serializer(existing)
            return Response(serializer.data, status=status.HTTP_200_OK)

        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError:
            # Защита от редкой гонки:
            # два одинаковых запроса пришли почти одновременно.
            existing = None

            if external_id:
                existing = Match.objects.filter(external_id=external_id).first()

            if not existing and external_match_key:
                existing = Match.objects.filter(external_match_key=external_match_key).first()

            if existing:
                serializer = self.get_serializer(existing)
                return Response(serializer.data, status=status.HTTP_200_OK)

            raise

    def perform_create(self, serializer):
        actor = self.request.user if self.request.user.is_authenticated else None

        with transaction.atomic():
            match: Match = serializer.save(status=Match.Status.DRAFT)

            # Капитаны тоже должны входить в свои команды.
            # Бот обычно передаёт team_1/team_2 без капитанов,
            # поэтому добавляем их на уровне API.
            if match.captain_1_id:
                match.team_1.add(match.captain_1_id)

            if match.captain_2_id:
                match.team_2.add(match.captain_2_id)

            log_match_event(
                match,
                MatchEvent.Type.CREATED,
                actor=actor,
                map=match.map_name,
                mode=match.mode,
                is_ranked=match.is_ranked,
                lobby_id=match.lobby_id,
                lobby_name=match.lobby_name,
                discord_guild_id=match.discord_guild_id,
                discord_channel_id=match.discord_channel_id,
            )

    @action(detail=True, methods=["post"])
    def mark_ready(self, request, pk=None):
        actor = request.user if request.user.is_authenticated else None

        with transaction.atomic():
            match = Match.objects.select_for_update().get(pk=self.get_object().pk)

            if match.status == Match.Status.READY:
                serializer = self.get_serializer(match)
                return Response(serializer.data, status=status.HTTP_200_OK)

            if match.status != Match.Status.DRAFT:
                return Response(
                    {"detail": f"Match cannot be marked ready from status '{match.status}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            match.status = Match.Status.READY
            match.save(update_fields=["status"])

            log_match_event(match, MatchEvent.Type.READY, actor=actor)

        serializer = self.get_serializer(match)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def start_match(self, request, pk=None):
        actor = request.user if request.user.is_authenticated else None

        with transaction.atomic():
            match = Match.objects.select_for_update().get(pk=self.get_object().pk)

            if match.status == Match.Status.IN_PROGRESS:
                serializer = self.get_serializer(match)
                return Response(serializer.data, status=status.HTTP_200_OK)

            if match.status != Match.Status.READY:
                return Response(
                    {"detail": f"Match cannot be started from status '{match.status}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            match.status = Match.Status.IN_PROGRESS
            match.save(update_fields=["status"])

            log_match_event(match, MatchEvent.Type.STARTED, actor=actor)

        serializer = self.get_serializer(match)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def cancel_match(self, request, pk=None):
        actor = request.user if request.user.is_authenticated else None

        with transaction.atomic():
            match = Match.objects.select_for_update().get(pk=self.get_object().pk)

            if match.status == Match.Status.FINISHED:
                return Response(
                    {"detail": "Finished match cannot be canceled."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if match.status == Match.Status.CANCELED:
                serializer = self.get_serializer(match)
                return Response(serializer.data, status=status.HTTP_200_OK)

            match.status = Match.Status.CANCELED
            match.finished_at = timezone.now()
            match.save(update_fields=["status", "finished_at"])

            log_match_event(match, MatchEvent.Type.CANCELED, actor=actor)

        serializer = self.get_serializer(match)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def set_winner(self, request, pk=None):
        serializer = SetWinnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        winner = int(serializer.validated_data["winner_team"])
        actor = request.user if request.user.is_authenticated else None

        with transaction.atomic():
            match = Match.objects.select_for_update().get(pk=self.get_object().pk)

            if match.winner_team is not None or match.status == Match.Status.FINISHED:
                return Response(
                    {"detail": "Winner already set."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if match.status != Match.Status.IN_PROGRESS:
                return Response(
                    {"detail": f"Winner can be set only for in-progress matches. Current status: '{match.status}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            team1_ids = set(match.team_1.values_list("id", flat=True))
            team2_ids = set(match.team_2.values_list("id", flat=True))

            if not team1_ids or not team2_ids:
                return Response(
                    {"detail": "Both teams must have players."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            winners_ids = team1_ids if winner == 1 else team2_ids
            losers_ids = team2_ids if winner == 1 else team1_ids

            duplicates = winners_ids & losers_ids
            if duplicates:
                logger.warning(
                    "Match %s: players present in both teams: %s",
                    match.id,
                    sorted(list(duplicates)),
                )
                losers_ids -= duplicates

            match.winner_team = winner
            match.status = Match.Status.FINISHED
            match.finished_at = timezone.now()
            match.save(update_fields=["winner_team", "status", "finished_at"])

            # Статистика/лидерборд только для ranked 5x5.
            if match.mode == Match.Mode.M5 and match.is_ranked:
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

            log_match_event(
                match,
                MatchEvent.Type.WIN_SET,
                actor=actor,
                winner_team=winner,
            )

        response_serializer = self.get_serializer(match)
        return Response(response_serializer.data, status=status.HTTP_200_OK)