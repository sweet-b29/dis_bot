import discord
from discord.ext import commands
from discord import app_commands
from modules.utils import api_client
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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
        username = username.strip()
        if not (1 <= len(username) <= 32):
            await interaction.response.send_message("❌ Ник должен быть 1–32 символа.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # 1) PATCH только username (без rank)
        try:
            await api_client.update_player_profile(
                discord_id=user.id,
                username=username,
                create_if_not_exist=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Не удалось обновить профиль в БД: {e}", ephemeral=True)
            return

        # 2) верифицируем чтением
        fresh = await api_client.get_player_profile(user.id)
        if fresh and fresh.get("username") == username:
            await interaction.followup.send(
                f"💾 Ник в профиле **обновлён**: {user.mention} → **{username}**.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "⚠ Ник в профиле не изменился. Проверь Django:\n"
                "• `players/serializers.py` — поле `username` включено в `fields` и `read_only=False`\n"
                "• `players/views.py` — PATCH идёт с `partial=True` и без принудительного требование `rank`\n"
                "• нет ли уникального конфликта по `username`",
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
        discord_id="ID игрока в Discord (правый клик → Copy ID)",
        duration="Длительность бана: 10m / 2h / 1d",
        reason="Причина бана"
    )
    async def ban(self, interaction: discord.Interaction, discord_id: str, duration: str, reason: str):
        await interaction.response.defer(thinking=True, ephemeral=True)

        # --- 1) Парсим длительность (10m / 2h / 1d)
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

        # --- 2) Время окончания бана в UTC (aware)
        now_utc = datetime.now(timezone.utc)
        expires_at = now_utc + delta  # aware UTC

        # --- 3) Вызываем API
        ok = await api_client.ban_player(
            discord_id=int(discord_id),
            expires_at=expires_at,
            reason=reason,
        )

        # --- 4) Готовим красивое сообщение с местным временем + остатком
        def humanize(td: timedelta) -> str:
            # нормализуем до положительного
            total = int(td.total_seconds())
            if total < 0:
                total = 0
            d, rem = divmod(total, 86400)
            h, rem = divmod(rem, 3600)
            m, _ = divmod(rem, 60)
            out = []
            if d: out.append(f"{d}д")
            if h: out.append(f"{h}ч")
            if m or not out: out.append(f"{m}м")
            return " ".join(out)

        # локальная таймзона
        tz_name = os.getenv("BOT_TZ", "Asia/Almaty")
        try:
            local_tz = ZoneInfo(tz_name)
        except Exception:
            local_tz = ZoneInfo("UTC")
            tz_name = "UTC"

        local_exp = expires_at.astimezone(local_tz)
        left_str = humanize(expires_at - now_utc)

        if ok:
            # Примеры: 15 авг 2025, 10:18 (Asia/Almaty, UTC+6) — осталось: 1д 2ч 5м
            utc_str = expires_at.strftime("%Y-%m-%d %H:%M UTC")
            local_str = local_exp.strftime("%Y-%m-%d %H:%M")
            # смещение в часах для красоты
            offset_hours = int(local_exp.utcoffset().total_seconds() // 3600)
            sign = "+" if offset_hours >= 0 else "-"
            offset_fmt = f"UTC{sign}{abs(offset_hours)}"

            msg = (
                f"✅ Игрок `{discord_id}` забанен до **{local_str}** "
                f"(*{tz_name}, {offset_fmt}*). Осталось: **{left_str}**.\n"
                f"🕒 UTC: {utc_str}\n"
                f"📝 Причина: **{reason}**"
            )
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.followup.send("❌ Не удалось выдать бан. Возможно, профиль не найден.", ephemeral=True)

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
