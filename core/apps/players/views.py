from django.utils import timezone
from loguru import logger
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAdminUser
from .models import Player, PlayerBan
from .serializers import PlayerSerializer, PlayerBanSerializer


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
        top_players = Player.objects.order_by('-wins')[:10]
        serializer = self.get_serializer(top_players, many=True)
        return Response(serializer.data)

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

    @action(detail=False, methods=['patch'], url_path='update_profile')
    def update_profile(self, request):
        data = request.data
        discord_id = data.get("discord_id")
        username = data.get("username", None)
        rank = data.get("rank", None)
        create_if_not_exist = data.get("create_if_not_exist", False)

        logger.warning(f"📥 PATCH /players/update_profile/ получен с данными: {data}")

        if not discord_id:
            return Response({"error": "discord_id is required"}, status=400)
        if username is None and rank is None:
            return Response({"error": "nothing to update (provide username or rank)"}, status=400)

        # пробуем найти игрока
        try:
            player = Player.objects.get(discord_id=discord_id)
            created = False
        except Player.DoesNotExist:
            # создаём только если разрешено и есть username
            if str(create_if_not_exist).lower() in ("true", "1", "yes"):
                if not username:
                    return Response({"error": "username required to create a profile"}, status=400)
                player = Player.objects.create(
                    discord_id=discord_id,
                    username=username,
                    rank=rank or Player._meta.get_field("rank").default or "Unranked",
                )
                created = True
            else:
                return Response({"error": "Player not found"}, status=404)

        # частичное обновление
        if username is not None:
            player.username = username
        if rank is not None:
            player.rank = rank

        try:
            player.save()
            if created:
                logger.success(f"✅ Создан новый игрок: {player.discord_id} - {player.username} ({player.rank})")
            else:
                logger.info(f"✏ Обновлён профиль игрока: {player.discord_id} - {player.username} ({player.rank})")
        except Exception as e:
            logger.error(f"❌ Ошибка при сохранении игрока {discord_id}: {e}")
            return Response({"error": "save failed"}, status=500)

        serializer = self.get_serializer(player)
        return Response(serializer.data, status=201 if created else 200)


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