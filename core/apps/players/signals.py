from allauth.account.signals import user_signed_up, user_logged_in
from allauth.socialaccount.models import SocialAccount
from django.dispatch import receiver

from .models import Player


def _discord_display_name(extra_data: dict) -> str:
    return (
        extra_data.get("global_name")
        or extra_data.get("username")
        or ""
    ).strip()


def _sync_discord_player(user):
    try:
        social_account = SocialAccount.objects.get(user=user, provider="discord")
    except SocialAccount.DoesNotExist:
        return

    extra_data = social_account.extra_data or {}
    discord_id = extra_data.get("id")

    if not discord_id:
        return

    player = Player.objects.filter(discord_id=discord_id).first()

    if player:
        player.user = user

        # Не перетираем Riot ID, если он уже заполнен.
        if not player.username:
            player.username = _discord_display_name(extra_data)

        player.save(update_fields=["user", "username"])
        return

    Player.objects.create(
        user=user,
        discord_id=discord_id,
        username=_discord_display_name(extra_data),
    )


@receiver(user_signed_up)
def create_player_on_signup(request, user, **kwargs):
    _sync_discord_player(user)


@receiver(user_logged_in)
def link_discord_account_to_player(sender, request, user, **kwargs):
    _sync_discord_player(user)