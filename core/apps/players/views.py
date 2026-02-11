from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAdminUser
from .models import Player, PlayerBan
from .serializers import PlayerSerializer, PlayerBanSerializer
from django.db.models import F, FloatField, ExpressionWrapper, Case, When, Value


class PlayerViewSet(viewsets.ModelViewSet):
    queryset = Player.objects.all()
    serializer_class = PlayerSerializer
    lookup_field = 'discord_id'

    @action(detail=True, methods=['post'])
    def add_win(self, request, discord_id=None):
        try:
            player = self.get_object()
            player.wins += 1
            player.matches += 1
            player.save()
            serializer = self.get_serializer(player)
            return Response(serializer.data)
        except Player.DoesNotExist:
            return Response({'error': 'Player not found'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['get'], url_path='top10')
    def top10(self, request):
        return self._leaderboard(limit=10)

    @action(detail=False, methods=['get'], url_path='leaderboard')
    def leaderboard(self, request):
        # алиас, чтобы бот мог звать /players/leaderboard/
        return self._leaderboard(limit=10)

    def _leaderboard(self, limit: int):
        qs = Player.objects.annotate(
            winrate=Case(
                When(matches__gt=0,
                     then=ExpressionWrapper(100.0 * F('wins') / F('matches'), output_field=FloatField())),
                default=Value(0.0), output_field=FloatField(),
            )
        ).order_by('-wins', '-winrate', '-matches', 'username')[:limit]

        data = [{
            "discord_id": p.discord_id,
            "username": p.username,
            "rank": p.rank,
            "wins": p.wins,
            "matches": p.matches,
            "winrate": round(p.winrate, 1),
        } for p in qs]
        return Response(data)

    @action(detail=True, methods=['post'], url_path='set_wins', lookup_field='discord_id')
    def set_wins(self, request, discord_id=None):
        try:
            player = self.get_object()
            new_wins = request.data.get("wins")
            if new_wins is None:
                return Response({'error': 'wins не передан'}, status=status.HTTP_400_BAD_REQUEST)

            player.wins = int(new_wins)
            player.save()
            serializer = self.get_serializer(player)
            return Response(serializer.data)
        except Player.DoesNotExist:
            return Response({'error': 'Player not found'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=["PATCH"], url_path="update_profile")
    def update_profile(self, request):
        """
        PATCH /players/update_profile/

        Тело:
        {
          "discord_id": 1234567890,
          "username": "Nick#TAG",   # опционально
          "rank": "Immortal 1",     # опционально
          "create_if_not_exist": true/false  # опционально (по умолчанию False)
        }
        """
        data = request.data

        discord_id = data.get("discord_id")
        username = data.get("username")
        rank = data.get("rank")
        create_if_not_exist = bool(data.get("create_if_not_exist", False))

        if not discord_id:
            return Response({"error": "discord_id is required"}, status=400)

        if username is None and rank is None:
            return Response(
                {"error": "nothing to update (provide username or rank)"},
                status=400,
            )

        # Ищем или создаём игрока
        player = Player.objects.filter(discord_id=discord_id).first()
        created = False

        if not player:
            if not create_if_not_exist:
                return Response(
                    {"error": "player not found and create_if_not_exist is False"},
                    status=404,
                )
            player = Player(discord_id=discord_id)
            created = True

        # Если пришёл username — обновляем и сбрасываем статистику по имени
        if username is not None:
            username = username.strip()
            if len(username) > 64:
                return Response({"error": "username too long"}, status=400)

            if player.username != username:
                player.username = username
                player.last_name_change = None  # можно потом реализовать логику отсечки по времени

        # Если пришёл rank — просто обновляем + обновляем время sync
        if rank is not None:
            rank = rank.strip()
            if len(rank) > 64:
                return Response({"error": "rank too long"}, status=400)

            player.rank = rank
            player.rank_last_sync = None  # время синка проставит фон/бот при следующем запросе

        try:
            player.save()
        except Exception as e:
            return Response({"error": str(e)}, status=500)

        serializer = PlayerSerializer(player)
        status_code = 201 if created else 200
        return Response(serializer.data, status=status_code)

    @action(
        detail=False,
        methods=["post"],
        url_path="reset_stats",
        authentication_classes=[TokenAuthentication],
        permission_classes=[IsAdminUser],
    )
    def reset_stats(self, request):
        updated = Player.objects.update(
            wins=0,
            matches=0,
            rank="Unranked",
            last_name_change=None,
            rank_last_sync=None,
        )
        return Response({"ok": True, "updated": updated})

    @action(
        detail=False,
        methods=["post"],
        url_path="wipe_players",
        authentication_classes=[TokenAuthentication],
        permission_classes=[IsAdminUser],
    )
    def wipe_players(self, request):
        deleted, _ = Player.objects.all().delete()
        return Response({"ok": True, "deleted": deleted})


class PlayerBanViewSet(viewsets.ModelViewSet):
    queryset = PlayerBan.objects.all()
    serializer_class = PlayerBanSerializer
    permission_classes = [permissions.IsAdminUser]
    authentication_classes = [TokenAuthentication]

    def perform_create(self, serializer):
        serializer.save(banned_by=self.request.user)

    @action(detail=False, methods=['get'], url_path='is_banned')
    def is_banned(self, request):
        discord_id = request.query_params.get("discord_id")
        if not discord_id:
            return Response({"error": "discord_id is required"}, status=400)

        try:
            player = Player.objects.get(discord_id=discord_id)
        except Player.DoesNotExist:
            return Response({"banned": False})

        active_ban = player.bans.filter(expires_at__gt=timezone.now()).first()
        if active_ban:
            return Response({
                "banned": True,
                "reason": active_ban.reason,
                "expires_at": active_ban.expires_at
            })

        return Response({"banned": False})