from django.contrib import admin
from django.utils.safestring import mark_safe
from .models import Match, MatchEvent

class MatchEventInline(admin.TabularInline):
    model = MatchEvent
    extra = 0
    readonly_fields = ("type", "actor", "data", "created_at")
    can_delete = False
    show_change_link = True

@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("id", "map_name", "winner_team", "created_at", "captain_1", "captain_2")
    list_filter = ("winner_team", "map_name", "created_at")
    search_fields = ("id", "captain_1__username", "captain_2__username")
    date_hierarchy = "created_at"
    inlines = (MatchEventInline,)
    readonly_fields = ("created_at",)

@admin.register(MatchEvent)
class MatchEventAdmin(admin.ModelAdmin):
    list_display = ("id", "match", "type", "created_at", "actor", "short_data")
    list_filter = ("type", "created_at")
    search_fields = ("match__id", "actor__username")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)

    def short_data(self, obj):
        import json
        text = json.dumps(obj.data, ensure_ascii=False, indent=2)[:300]
        return mark_safe(f"<pre style='white-space:pre-wrap'>{text}</pre>")
