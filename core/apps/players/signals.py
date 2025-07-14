from allauth.account.signals import user_signed_up, user_logged_in
from django.dispatch import receiver
from allauth.socialaccount.models import SocialAccount
from .models import Player


@receiver(user_signed_up)
def create_player_on_signup(request, user, **kwargs):
    try:
        social_account = SocialAccount.objects.get(user=user, provider='discord')
        discord_id = social_account.extra_data.get("id")

        if discord_id:
            Player.objects.create(user=user, discord_id=discord_id)
    except SocialAccount.DoesNotExist:
        pass


@receiver(user_logged_in)
def link_discord_account_to_player(sender, request, user, **kwargs):
    try:
        social_account = SocialAccount.objects.get(user=user, provider='discord')
        discord_id = social_account.extra_data.get("id")

        if discord_id:
            Player.objects.update_or_create(
                discord_id=discord_id,
                defaults={"user": user}
            )
    except SocialAccount.DoesNotExist:
        pass
