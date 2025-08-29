from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Match
from .serializers import MatchSerializer, SetWinnerSerializer
from django.db import transaction


class MatchViewSet(viewsets.ModelViewSet):
    queryset = Match.objects.all().order_by('-created_at')
    serializer_class = MatchSerializer

    @action(detail=True, methods=['post'])
    def set_winner(self, request, pk=None):
        match = self.get_object()
        serializer = SetWinnerSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        winner = serializer.validated_data['winner_team']

        winners_qs = match.team_1.all() if winner == 1 else match.team_2.all()
        losers_qs = match.team_2.all() if winner == 1 else match.team_1.all()

        with transaction.atomic():
            match.winner_team = winner
            match.save(update_fields=["winner_team"])

            for player in winners_qs.select_for_update():
                player.wins += 1
                player.matches += 1
                player.save(update_fields=["wins", "matches"])

            for player in losers_qs.select_for_update():
                player.matches += 1
                player.save(update_fields=["matches"])

        return Response({'status': 'updated'}, status=status.HTTP_200_OK)