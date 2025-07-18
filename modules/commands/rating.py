from pathlib import Path
import discord
from discord.ext import commands
from discord import app_commands
from modules.utils import api_client
import os

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
        if not isinstance(data, list):
            await interaction.followup.send("❌ Не удалось загрузить таблицу лидеров.", ephemeral=True)
            return

        # 📦 Генерация Embed и прикрепление баннера
        embed = await self.build_embed(data)

        banner_path = Path(__file__).resolve().parents[2] / "modules" / "pictures" / "leaderboard.jpg"
        if not banner_path.exists():
            print(f"⚠ Баннер не найден по пути: {banner_path}")
            return await interaction.followup.send("❌ Баннер не найден.", ephemeral=True)

        banner_file = discord.File(banner_path, filename="leaderboard.jpg")
        embed.set_image(url="attachment://leaderboard.jpg")

        view = Top10View(self)

        await interaction.followup.send(embed=embed, file=banner_file, view=view)

    async def build_embed(self, data):
        embed = discord.Embed(
            title="🏆 Топ-10 игроков по победам",
            description="",
            color=discord.Color.orange()
        )

        medals = ["🥇", "🥈", "🥉"]
        for i, player in enumerate(data[:3]):
            username = player.get("username", "—")
            discord_id = int(player.get("discord_id", 0))
            wins = player.get("wins", 0)

            name = f"{medals[i]} **{username}**"
            value = f"<@{discord_id}> — **{wins} побед**"
            embed.add_field(name=name, value=value, inline=False)

        for player in data[3:]:
            username = player.get("username", "—")
            discord_id = int(player.get("discord_id", 0))
            wins = player.get("wins", 0)

            embed.add_field(
                name=username,
                value=f"<@{discord_id}> — {wins} побед",
                inline=False
            )

        embed.set_footer(text="🔄 Обновите список, чтобы получить актуальные данные")
        embed.set_image(url="attachment://leaderboard.jpg")
        return embed


class Top10View(discord.ui.View):
    def __init__(self, rating_cog):
        super().__init__(timeout=None)
        self.rating_cog = rating_cog

    @discord.ui.button(label="🔄 Обновить", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        data = await api_client.get_top10_players()
        if not isinstance(data, list):
            await interaction.followup.send("❌ Не удалось обновить список лидеров.", ephemeral=True)
            return

        embed = await self.rating_cog.build_embed(data)

        banner_path = Path(__file__).resolve().parents[2] / "modules" / "pictures" / "leaderboard.jpg"
        if banner_path.exists():
            banner_file = discord.File(banner_path, filename="leaderboard.jpg")
            embed.set_image(url="attachment://leaderboard.jpg")
            await interaction.followup.send(embed=embed, file=banner_file, view=self)
        else:
            await interaction.followup.send("❌ Баннер не найден.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Rating(bot))