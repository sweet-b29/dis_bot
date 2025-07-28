import discord
from discord.ext import commands
from discord import app_commands
from modules.utils import api_client
import os
import datetime

GUILD_ID = int(os.getenv("GUILD_ID", 0))
ALLOWED_ROLES = list(map(int, os.getenv("ALLOWED_ROLES", "").split(",")))

@app_commands.guilds(discord.Object(id=GUILD_ID))
class Admin(commands.GroupCog, name="admin"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        return any(role.id in ALLOWED_ROLES for role in interaction.user.roles)

    @app_commands.command(name="changerank", description="Изменить ранг и Riot-ник игрока")
    @app_commands.describe(user="Участник", rank="Ранг", username="Riot-ник (опционально)")
    async def changerank(self, interaction: discord.Interaction, user: discord.Member, rank: str, username: str = None):
        username = username or user.display_name
        await api_client.update_player_profile(user.id, username, rank.capitalize())
        await interaction.response.send_message(
            f"✏️ Обновлён профиль {user.mention}: **{username}**, ранг **{rank.capitalize()}**",
            ephemeral=True
        )

    @app_commands.command(name="changenick", description="Изменить Riot-ник игрока")
    @app_commands.describe(user="Участник", username="Новый Riot-ник")
    async def changenick(self, interaction: discord.Interaction, user: discord.Member, username: str):
        profile = await api_client.get_all_players()
        if any(p['discord_id'] == user.id for p in profile):
            await api_client.update_player_profile(user.id, username, None)
            await interaction.response.send_message(
                f"🔁 Ник игрока {user.mention} изменён на **{username}**.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ Профиль игрока {user.mention} не найден.",
                ephemeral=True
            )

    @app_commands.command(name="changewins", description="Установить количество побед игрока")
    @app_commands.describe(user="Участник", wins="Новое количество побед")
    async def changewins(self, interaction: discord.Interaction, user: discord.Member, wins: int):
        await api_client.set_player_wins(user.id, wins)
        await interaction.response.send_message(
            f"🏆 Победы {user.mention} установлены на **{wins}**.",
            ephemeral=True
        )

    @app_commands.command(name="ban", description="Забанить игрока по Discord ID")
    @app_commands.describe(
        discord_id="ID игрока в Discord (правый клик > Copy ID)",
        duration="Длительность бана (например: 10m, 2h, 1d)",
        reason="Причина бана"
    )
    async def ban(self, interaction: discord.Interaction, discord_id: str, duration: str, reason: str):
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            if duration.endswith("m"):
                delta = datetime.timedelta(minutes=int(duration[:-1]))
            elif duration.endswith("h"):
                delta = datetime.timedelta(hours=int(duration[:-1]))
            elif duration.endswith("d"):
                delta = datetime.timedelta(days=int(duration[:-1]))
            else:
                await interaction.followup.send("❌ Формат времени: 10m / 2h / 1d")
                return
        except Exception:
            await interaction.followup.send("❌ Не удалось обработать длительность.")
            return

        expires_at = datetime.datetime.now() + delta
        success = await api_client.ban_player(
            discord_id=int(discord_id),
            expires_at=expires_at,
            reason=reason,
            banned_by_id=interaction.user.id
        )

        if success:
            await interaction.followup.send(
                f"✅ Игрок `{discord_id}` забанен до `{expires_at.strftime('%Y-%m-%d %H:%M')}` по причине: **{reason}**"
            )
        else:
            await interaction.followup.send("❌ Не удалось выдать бан. Возможно, не найден профиль.")

    @app_commands.command(name="adminhelp", description="Показать команды администратора")
    async def adminhelp(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔧 Админ-команды",
            description="Список доступных команд:",
            color=discord.Color.red()
        )
        embed.add_field(name="/admin changerank", value="✏ Изменить ранг", inline=False)
        embed.add_field(name="/admin changenick", value="🔁 Изменить Riot-ник", inline=False)
        embed.add_field(name="/admin changewins", value="🏆 Установить победы", inline=False)
        embed.add_field(name="/admin ban", value="🔐 Забанить игрока", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Admin(bot))
