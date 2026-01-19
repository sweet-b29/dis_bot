import csv
from django.contrib import admin
from django.http import HttpResponse

from .models import Player, PlayerBan, Season, PlayerSeasonStat


@admin.action(description="Export selected players to CSV")
def export_players_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="players_export.csv"'
    writer = csv.writer(response)

    writer.writerow(["discord_id", "username", "rank", "wins", "matches", "winrate_%", "last_name_change"])

    for p in queryset:
        matches = int(p.matches or 0)
        wins = int(p.wins or 0)
        winrate = round((wins / matches) * 100, 2) if matches else 0.0
        writer.writerow([p.discord_id, p.username, p.rank, wins, matches, winrate, p.last_name_change])

    return response


class PlayerSeasonStatInline(admin.TabularInline):
    model = PlayerSeasonStat
    extra = 0
    can_delete = False
    readonly_fields = ("discord_id", "username", "rank", "wins", "matches", "captured_at")
    fields = ("discord_id", "username", "rank", "wins", "matches", "captured_at")


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("name", "started_at", "ended_at", "created_at")
    search_fields = ("name",)
    inlines = [PlayerSeasonStatInline]


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("discord_id", "username", "rank", "wins", "matches")
    search_fields = ("username", "discord_id")
    list_filter = ("rank",)
    actions = [export_players_csv]


@admin.register(PlayerBan)
class PlayerBanAdmin(admin.ModelAdmin):
    list_display = ("player", "player_discord_id", "expires_at", "reason")
    search_fields = ("player__discord_id", "player__username")
    list_filter = ("expires_at",)

    @admin.display(description="discord_id")
    def player_discord_id(self, obj):
        return getattr(obj.player, "discord_id", None)

