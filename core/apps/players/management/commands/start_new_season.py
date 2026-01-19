from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.apps import apps

from apps.players.models import Player, PlayerBan, Season, PlayerSeasonStat


def get_model(app_labels: list[str], model_name: str):
    for label in app_labels:
        try:
            return apps.get_model(label, model_name)
        except LookupError:
            pass
    return None


class Command(BaseCommand):
    help = "Archive current player stats into a Season and reset the system (optionally wiping players/matches)."

    def add_arguments(self, parser):
        parser.add_argument("--name", type=str, default=None, help="Season name, e.g. 'Season 1'")
        parser.add_argument("--wipe-players", action="store_true", help="Delete all players after archiving (forces re-registration).")
        parser.add_argument("--wipe-matches", action="store_true", help="Delete all matches after archiving.")

    @transaction.atomic
    def handle(self, *args, **options):
        name = options["name"] or f"Season {timezone.now().strftime('%Y-%m-%d %H:%M')}"
        wipe_players = options["wipe_players"]
        wipe_matches = options["wipe_matches"]

        season = Season.objects.create(name=name, ended_at=timezone.now())

        # snapshot stats
        stats = []
        for p in Player.objects.all().only("discord_id", "username", "rank", "wins", "matches"):
            stats.append(PlayerSeasonStat(
                season=season,
                discord_id=p.discord_id,
                username=p.username,
                rank=p.rank,
                wins=p.wins,
                matches=p.matches,
            ))
        PlayerSeasonStat.objects.bulk_create(stats, batch_size=1000)

        # wipe matches/events if requested
        if wipe_matches:
            MatchEvent = get_model(["apps.matches", "matches"], "MatchEvent")
            Match = get_model(["apps.matches", "matches"], "Match")

            if MatchEvent:
                MatchEvent.objects.all().delete()
            if Match:
                Match.objects.all().delete()

        # wipe bans always (обычно логично начинать сезон без банов)
        PlayerBan.objects.all().delete()

        # wipe players if requested (forces re-registration)
        if wipe_players:
            Player.objects.all().delete()
        else:
            Player.objects.all().update(wins=0, matches=0)

        self.stdout.write(self.style.SUCCESS(
            f"OK: season='{season.name}', archived={len(stats)}, wipe_players={wipe_players}, wipe_matches={wipe_matches}"
        ))
