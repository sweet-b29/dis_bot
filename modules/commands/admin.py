import os
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from modules.utils import api_client


def _parse_role_ids(env_name: str) -> list[int]:
    raw = os.getenv(env_name, "")
    result: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            continue
    return result


ALLOWED_ROLES: list[int] = _parse_role_ids("ALLOWED_ROLES")


def admin_only():
    """
    Доступ:
    - всегда разрешаем Discord Administrator
    - иначе проверяем роли из ALLOWED_ROLES
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        user = interaction.user

        # safety
        if not isinstance(user, discord.Member):
            return False

        # админ сервера всегда может
        if user.guild_permissions.administrator:
            return True

        # если список ролей пуст — значит доступ закрыт всем, кроме администратора
        if not ALLOWED_ROLES:
            return False

        return any(role.id in ALLOWED_ROLES for role in user.roles)

    return app_commands.check(predicate)


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="changerank", description="Изменить ранг игрока (без изменения ника)")
    @app_commands.describe(user="Участник", rank="Ранг (например: Immortal 2)")
    @admin_only()
    async def changerank(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        rank: str,
    ):
        rank = rank.strip()
        if not (1 <= len(rank) <= 32):
            await interaction.response.send_message("❌ Ранг должен быть 1–32 символа.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await api_client.update_player_profile(discord_id=user.id, username=None, rank=rank)
        except Exception as e:
            await interaction.followup.send(f"❌ Не удалось обновить ранг в БД: {e}", ephemeral=True)
            return

        await interaction.followup.send(f"✅ Ранг обновлён: {user.mention} → **{rank}**", ephemeral=True)

    @app_commands.command(name="changenick", description="Изменить Riot-ник игрока (без изменения ранга)")
    @app_commands.describe(user="Участник", username="Новый Riot-ник")
    @admin_only()
    async def changenick(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        username: str,
    ):
        username = username.strip()
        if not (1 <= len(username) <= 32):
            await interaction.response.send_message("❌ Ник должен быть 1–32 символа.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # 1) PATCH только username (без rank)
        try:
            await api_client.update_player_profile(discord_id=user.id, username=username, rank=None)
        except Exception as e:
            await interaction.followup.send(f"❌ Не удалось обновить ник в БД: {e}", ephemeral=True)
            return

        # 2) контрольное чтение
        try:
            fresh = await api_client.get_player_profile(user.id)
        except Exception:
            fresh = {}

        if fresh and fresh.get("username") == username:
            await interaction.followup.send(
                f"✅ Ник обновлён: {user.mention} → **{username}**",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "⚠ Ник не подтвердился чтением из API. Проверь Django:\n"
                "• `players/serializers.py` — поле `username` не read-only\n"
                "• `players/views.py` — PATCH с `partial=True`\n",
                ephemeral=True
            )

    @app_commands.command(name="changewins", description="Установить количество побед игрока")
    @app_commands.describe(user="Участник", wins="Новое количество побед")
    @admin_only()
    async def changewins(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        wins: int,
    ):
        if wins < 0:
            await interaction.response.send_message("❌ Победы не могут быть отрицательными.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await api_client.set_player_wins(user.id, wins)
        except Exception as e:
            await interaction.followup.send(f"❌ Не удалось установить победы: {e}", ephemeral=True)
            return

        await interaction.followup.send(f"🏆 Победы установлены: {user.mention} → **{wins}**", ephemeral=True)

    @app_commands.command(name="ban", description="Забанить игрока по discord_id на время (10m/2h/1d)")
    @app_commands.describe(discord_id="Discord ID игрока", duration="Длительность: 10m/2h/1d", reason="Причина")
    @admin_only()
    async def ban(
        self,
        interaction: discord.Interaction,
        discord_id: str,
        duration: str,
        reason: str = "No reason",
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        s = duration.strip().lower()
        if len(s) < 2 or not s[:-1].isdigit() or s[-1] not in ("m", "h", "d"):
            await interaction.followup.send("❌ Неверный формат. Используй: `10m`, `2h`, `1d`.", ephemeral=True)
            return

        n = int(s[:-1])
        unit = s[-1]
        if unit == "m":
            delta = timedelta(minutes=n)
        elif unit == "h":
            delta = timedelta(hours=n)
        else:
            delta = timedelta(days=n)

        now_utc = datetime.now(timezone.utc)
        expires_at = now_utc + delta

        try:
            ok = await api_client.ban_player(
                discord_id=int(discord_id),
                expires_at=expires_at,
                reason=reason,
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка при бане: {e}", ephemeral=True)
            return

        if ok:
            await interaction.followup.send(
                f"🔐 Бан выдан: **{discord_id}**\n"
                f"⏳ До: **{expires_at.isoformat()}** (UTC)\n"
                f"📝 Причина: **{reason}**",
                ephemeral=True
            )
        else:
            await interaction.followup.send("❌ Не удалось выдать бан. Возможно, профиль не найден.", ephemeral=True)

    @app_commands.command(name="adminhelp", description="Показать команды администратора")
    @admin_only()
    async def adminhelp(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔧 Админ-команды",
            description="Доступны верхнеуровневые команды:",
            color=discord.Color.red()
        )
        embed.add_field(name="/changerank", value="Изменить ранг игрока", inline=False)
        embed.add_field(name="/changenick", value="Изменить Riot-ник игрока", inline=False)
        embed.add_field(name="/changewins", value="Установить победы игрока", inline=False)
        embed.add_field(name="/ban", value="Бан по discord_id на время", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
