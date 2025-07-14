from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Match
from .serializers import MatchSerializer, SetWinnerSerializer


class MatchViewSet(viewsets.ModelViewSet):
    queryset = Match.objects.all().order_by('-created_at')
    serializer_class = MatchSerializer

    @action(detail=True, methods=['post'])
    def set_winner(self, request, pk=None):
        match = self.get_object()
        serializer = SetWinnerSerializer(data=request.data)
        if serializer.is_valid():
            winner = serializer.validated_data['winner_team']
            match.winner_team = winner
            match.save()

            team = match.team_1.all() if winner == 1 else match.team_2.all()

            for player in team:
                player.wins += 1
                player.matches += 1
                player.save()

            # Для проигравших
            losers = match.team_2.all() if winner == 1 else match.team_1.all()
            for player in losers:
                player.matches += 1
                player.save()

            return Response({'status': 'updated'}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)