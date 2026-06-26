from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.players.models import Player, Season, PlayerSeasonStat


class Command(BaseCommand):
    help = (
        "Close current season: archive player stats into PlayerSeasonStat "
        "and reset wins/matches without deleting players, matches or bans."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            type=str,
            required=True,
            help="Season name, e.g. 'Season 1'",
        )
        parser.add_argument(
            "--confirm",
            type=str,
            required=True,
            help="Must be CONFIRM to run this command.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        season_name = str(options["name"]).strip()
        confirm = str(options["confirm"]).strip()

        if confirm != "CONFIRM":
            raise CommandError("To close season, pass: --confirm CONFIRM")

        if not season_name:
            raise CommandError("Season name cannot be empty.")

        if Season.objects.filter(name=season_name).exists():
            raise CommandError(f"Season '{season_name}' already exists.")

        players = list(
            Player.objects.all().only(
                "discord_id",
                "username",
                "rank",
                "wins",
                "matches",
            )
        )

        if not players:
            raise CommandError("No players found. Season was not created.")

        season = Season.objects.create(
            name=season_name,
            ended_at=timezone.now(),
        )

        season_stats = [
            PlayerSeasonStat(
                season=season,
                discord_id=p.discord_id,
                username=p.username or "",
                rank=p.rank or "Unranked",
                wins=int(p.wins or 0),
                matches=int(p.matches or 0),
            )
            for p in players
        ]

        PlayerSeasonStat.objects.bulk_create(
            season_stats,
            batch_size=1000,
        )

        reset_count = Player.objects.update(
            wins=0,
            matches=0,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Season closed: '{season.name}'. "
                f"Archived players: {len(season_stats)}. "
                f"Reset players: {reset_count}."
            )
        )