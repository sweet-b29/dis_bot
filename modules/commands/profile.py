import discord
from discord import app_commands
from discord.ext import commands

from modules.utils import api_client
from modules.utils.rank_sync import ensure_fresh_rank
from modules.utils.image_generator import generate_profile_card
from modules.utils.valorant_api import ValorantRankError


async def send_profile_card(interaction: discord.Interaction, *, edit: bool = False):
    """
    edit=False  -> отправляет новое сообщение
    edit=True   -> редактирует текущее (для кнопки "Обновить")
    """
    discord_id = interaction.user.id

    # 1) Получаем профиль (и пытаемся подтянуть ранг)
    try:
        profile = await ensure_fresh_rank(discord_id, force=False)
    except ValorantRankError:
        # если HenrikDev в лимите — просто показываем то, что уже есть в БД
        profile = await api_client.get_player(discord_id)

    if not profile:
        profile = {"username": None, "rank": "Unranked", "wins": 0}

    username = profile.get("username") or "Не указан"
    rank = profile.get("rank") or "Unranked"
    wins = int(profile.get("wins") or 0)

    # 2) Аватар
    avatar_bytes = await interaction.user.display_avatar.read()

    # 3) Генерация картинки
    out_path = generate_profile_card(
        discord_id=discord_id,
        username=username,
        wins=wins,
        rank=rank,
        avatar_bytes=avatar_bytes,
    )

    file = discord.File(out_path, filename="profile.png")
    embed = discord.Embed(title="Профиль игрока")
    embed.set_image(url="attachment://profile.png")

    view = ProfileView(discord_id=discord_id)

    # 4) Ответ interaction (аккуратно: response может быть уже использован)
    if edit:
        if interaction.response.is_done():
            await interaction.edit_original_response(attachments=[file], embed=embed, view=view)
        else:
            await interaction.response.edit_message(attachments=[file], embed=embed, view=view)
    else:
        if interaction.response.is_done():
            await interaction.followup.send(file=file, embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(file=file, embed=embed, view=view, ephemeral=True)


class ProfileView(discord.ui.View):
    def __init__(self, discord_id: int):
        super().__init__(timeout=120)
        self.discord_id = discord_id

    @discord.ui.button(label="🔄 Обновить", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await send_profile_card(interaction, edit=True)

    @discord.ui.button(label="✏️ Редактировать", style=discord.ButtonStyle.primary)
    async def edit_profile(self, interaction: discord.Interaction, _: discord.ui.Button):
        # локальный импорт, чтобы не словить циклические импорты
        from modules.lobby import PlayerProfileModal
        await interaction.response.send_modal(PlayerProfileModal(interaction))


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profile", description="Показать профиль игрока")
    async def profile(self, interaction: discord.Interaction):
        await send_profile_card(interaction, edit=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))