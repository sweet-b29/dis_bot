import os
import discord
from discord.ext import commands
from discord import app_commands
from modules.utils import api_client
from modules.utils.image_generator import generate_leaderboard_image

# 🔐 Чтение ALLOWED_ROLES
raw_roles = os.getenv("ALLOWED_ROLES", "")
try:
    ALLOWED_ROLES = list(map(int, raw_roles.split(","))) if raw_roles else []
    if not ALLOWED_ROLES:
        print("⚠ Внимание: ALLOWED_ROLES не указаны. Команда /leaderboard будет недоступна для всех.")
except ValueError:
    ALLOWED_ROLES = []
    print("⚠ Ошибка: ALLOWED_ROLES содержит недопустимые значения.")


class Rating(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="leaderboard", description="Показать топ-10 игроков по победам")
    async def leaderboard(self, interaction: discord.Interaction):
        if not any(role.id in ALLOWED_ROLES for role in interaction.user.roles):
            await interaction.response.send_message("❌ У вас нет доступа к этой команде.", ephemeral=True)
            return

        await interaction.response.defer()

        data = await api_client.get_top10_players()
        if not isinstance(data, list) or not data:
            await interaction.followup.send("❌ Не удалось загрузить таблицу лидеров.", ephemeral=True)
            return

        image_path = generate_leaderboard_image(data)
        file = discord.File(image_path, filename="leaderboard.png")

        view = Top10View()

        await interaction.followup.send(file=file, view=view)


class Top10View(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔄 Обновить", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        data = await api_client.get_top10_players()
        if not isinstance(data, list) or not data:
            await interaction.followup.send("❌ Не удалось обновить список лидеров.", ephemeral=True)
            return

        image_path = generate_leaderboard_image(data)
        file = discord.File(image_path, filename="leaderboard.png")

        await interaction.edit_original_response(attachments=[file])


async def setup(bot):
    await bot.add_cog(Rating(bot))
