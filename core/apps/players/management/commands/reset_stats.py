from django.core.management.base import BaseCommand
from django.db import transaction
from apps.players.models import Player


class Command(BaseCommand):
    help = "Reset wins/matches for all players without touching profiles."

    def handle(self, *args, **options):
        with transaction.atomic():
            updated = Player.objects.all().update(wins=0, matches=0)
        self.stdout.write(self.style.SUCCESS(f"✅ Reset stats for {updated} players"))
