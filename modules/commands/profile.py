import discord
from discord import app_commands
from discord.ext import commands

from modules.utils import api_client
from modules.utils.image_generator import generate_profile_card
from modules.utils.profile_setup import RiotIdModal


def _rank_base(rank: str | None) -> str:
    if not rank:
        return "Unranked"
    return rank.split()[0].lower()


def _rank_color(rank: str | None) -> discord.Color:
    base = _rank_base(rank)
    colors = {
        "iron": discord.Color.dark_gray(),
        "bronze": discord.Color.from_rgb(205, 127, 50),
        "silver": discord.Color.light_grey(),
        "gold": discord.Color.gold(),
        "platinum": discord.Color.teal(),
        "diamond": discord.Color.blue(),
        "ascendant": discord.Color.green(),
        "immortal": discord.Color.red(),
        "radiant": discord.Color.purple(),
        "unranked": discord.Color.blurple(),
    }
    return colors.get(base, discord.Color.blurple())


async def _get_profile(discord_id: int) -> dict:
    try:
        profile = await api_client.get_player_profile(discord_id)
        return profile or {}
    except Exception:
        return {}


async def _build_profile_payload(member: discord.abc.User) -> tuple[discord.Embed, discord.File]:
    profile = await _get_profile(member.id)

    username = profile.get("username") or "Не указан"
    rank = profile.get("rank") or "Unranked"
    wins = profile.get("wins") or 0
    matches = profile.get("matches") or 0

    embed = discord.Embed(
        title=f"Профиль: {member.display_name}",
        description=f"**Riot ID:** `{username}`\n**Ранг:** `{rank}`",
        color=_rank_color(rank),
    )
    embed.add_field(name="Победы", value=str(wins), inline=True)
    embed.add_field(name="Матчи", value=str(matches), inline=True)

    file = await generate_profile_card(member, {"username": username, "rank": rank, "wins": wins, "matches": matches})
    embed.set_image(url="attachment://profile.png")

    return embed, file


class ProfileView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=180)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Это меню не для тебя.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Редактировать", style=discord.ButtonStyle.primary)
    async def edit_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        profile = await _get_profile(interaction.user.id)
        default_riot = profile.get("username") if profile else None
        await interaction.response.send_modal(RiotIdModal(user_id=interaction.user.id, default_riot_id=default_riot))

    @discord.ui.button(label="Обновить", style=discord.ButtonStyle.secondary)
    async def refresh_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, file = await _build_profile_payload(interaction.user)
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profile", description="Показать профиль")
    async def profile(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed, file = await _build_profile_payload(interaction.user)
        await interaction.followup.send(embed=embed, file=file, view=ProfileView(interaction.user.id), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))