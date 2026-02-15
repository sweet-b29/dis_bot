from django import forms
from django.contrib import admin
from django.utils.safestring import mark_safe
from .models import Match, MatchEvent

# ----- форма c запретом дублей игрока в обеих командах -----
class MatchAdminForm(forms.ModelForm):
    class Meta:
        model = Match
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        t1 = set(cleaned.get("team_1").values_list("pk", flat=True)) if cleaned.get("team_1") else set()
        t2 = set(cleaned.get("team_2").values_list("pk", flat=True)) if cleaned.get("team_2") else set()
        dup = t1 & t2
        if dup:
            raise forms.ValidationError("Игрок не может входить в обе команды одного матча.")
        return cleaned

# ----- inline событий матча -----
class MatchEventInline(admin.TabularInline):
    model = MatchEvent
    extra = 0
    readonly_fields = ("type", "actor", "data", "created_at")
    can_delete = False
    show_change_link = True

# ----- единственная регистрация Match -----
@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    form = MatchAdminForm
    list_display = ("id", "mode", "lobby_name", "map_name", "winner_team", "created_at", "captain_1", "captain_2")
    list_filter = ("mode", "winner_team", "map_name", "created_at")
    search_fields = ("id", "lobby_name", "captain_1__username", "captain_2__username")
    date_hierarchy = "created_at"
    inlines = (MatchEventInline,)
    readonly_fields = ("created_at",)

# ----- регистрация событий -----
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
