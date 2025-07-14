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
        self.top10_message = None

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

        embed = await self.build_embed(data)

        try:
            banner = discord.File("media/top10_banner.webp")
        except FileNotFoundError:
            banner = None
            print("⚠ Баннер не найден: media/top10_banner.webp")

        view = Top10View(self)

        await interaction.followup.send(
            embed=embed,
            file=banner if banner else discord.utils.MISSING,
            view=view
        )

    async def build_embed(self, data):
        embed = discord.Embed(
            title="🏆 Топ-10 игроков по победам",
            description="",
            color=discord.Color.dark_gold()
        )

        medals = ["🥇", "🥈", "🥉"]
        for i, player in enumerate(data[:3]):
            username = player.get("username", "—")
            discord_id = int(player.get("discord_id", 0))  # 👈 обязательно
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

        embed.set_image(url="https://i.pinimg.com/736x/f9/e4/1b/f9e41b089d9b8aed2897dde90c4ea314.jpg")
        embed.set_footer(text="🔄 Обновите список, чтобы получить актуальные данные")
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

        try:
            banner = discord.File("media/top10_banner.webp")
        except FileNotFoundError:
            banner = None

        await interaction.message.edit(
            embed=embed,
            attachments=[banner] if banner else [],
            view=self
        )

async def setup(bot):
    await bot.add_cog(Rating(bot))
