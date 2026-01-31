import os
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from modules.utils import api_client

PRIZES_WEBHOOK_TEXT = (
    "Призы:\n"
    " 1️⃣ место <a:arrow:1388296844009930893> 9650 VP + роль \n"
    "2️⃣ место <a:arrow:1388296844009930893>** 4650 VP + роль** \n"
    "3️⃣ место <a:arrow:1388296844009930893>** 3225 VP + роль** \n"
    "4️⃣ место <a:arrow:1388296844009930893> 1825 VP \n"
    "5️⃣ место <a:arrow:1388296844009930893> 880 VP \n"
    "6️⃣ место <a:arrow:1388296844009930893> 420 VP \n\n"
    "ДОПОЛНИТЕЛЬНЫЕ КАТЕГОРИИ \n\n"
    "<:AnimeShooting:1320781753249435760> Лучший хайлайт <a:arrow:1388296844009930893> 1825 VP \n"
    "<:GamerRage:1320781742876921917>  Самый смешной момент <a:arrow:1388296844009930893> 1825 VP \n"
    "<:02yaygifemoji:1331568478808969246> Душа компании <a:arrow:1388296844009930893> 1825 VP"
)


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
    - владелец сервера
    - Discord Administrator
    - Manage Guild (часто у "админ" роли есть это право)
    - либо роли из ALLOWED_ROLES (id через запятую)
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        user = interaction.user

        if not isinstance(user, discord.Member):
            return False

        # owner всегда может
        if interaction.guild and user.id == interaction.guild.owner_id:
            return True

        perms = user.guild_permissions
        if perms.administrator:
            return True

        # "админ роль" часто без administrator, но с manage_guild
        if perms.manage_guild:
            return True

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
    async def changerank(self, interaction: discord.Interaction, user: discord.Member, rank: str):
        rank = rank.strip()
        if not (1 <= len(rank) <= 32):
            await interaction.response.send_message("❌ Ранг должен быть 1–32 символа.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            # если профиля нет — создаём (иначе будет 404)
            profile = await api_client.get_player_profile(user.id)
            if not profile:
                tmp_username = (user.display_name or user.name or "Player").strip()[:32]
                await api_client.update_player_profile(
                    discord_id=user.id,
                    username=tmp_username,
                    rank=rank,
                    create_if_not_exist=True,
                )
            else:
                await api_client.update_player_profile(
                    discord_id=user.id,
                    username=None,
                    rank=rank,
                    create_if_not_exist=False,
                )
        except Exception as e:
            await interaction.followup.send(f"❌ Не удалось обновить ранг в БД: {e}", ephemeral=True)
            return

        await interaction.followup.send(f"✅ Ранг обновлён: {user.mention} → **{rank}**", ephemeral=True)

    @app_commands.command(name="changenick", description="Изменить Riot-ник игрока (без изменения ранга)")
    @app_commands.describe(user="Участник", username="Новый Riot-ник")
    @admin_only()
    async def changenick(self, interaction: discord.Interaction, user: discord.Member, username: str):
        username = username.strip()
        if not (1 <= len(username) <= 32):
            await interaction.response.send_message("❌ Ник должен быть 1–32 символа.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            # создаём профиль при необходимости
            await api_client.update_player_profile(
                discord_id=user.id,
                username=username,
                rank=None,
                create_if_not_exist=True,
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Не удалось обновить ник в БД: {e}", ephemeral=True)
            return

        # контрольное чтение (не обязательно, но удобно)
        fresh = await api_client.get_player_profile(user.id)
        if fresh and fresh.get("username") == username:
            await interaction.followup.send(f"✅ Ник обновлён: {user.mention} → **{username}**", ephemeral=True)
        else:
            await interaction.followup.send("⚠ Ник отправлен, но API не подтвердило обновление.", ephemeral=True)

    @app_commands.command(name="changewins", description="Установить количество побед игрока")
    @app_commands.describe(user="Участник", wins="Новое количество побед")
    @admin_only()
    async def changewins(self, interaction: discord.Interaction, user: discord.Member, wins: int):
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
    async def ban(self, interaction: discord.Interaction, discord_id: str, duration: str, reason: str = "No reason"):
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
        embed.add_field(name="/prizeswebhook", value="Отправить сообщение о призах в webhook", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

@app_commands.command(name="prizeswebhook", description="Отправить сообщение о призах в заданный webhook")
    @admin_only()
    async def prizeswebhook(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        webhook_url = os.getenv("PRIZES_WEBHOOK_URL", "").strip()
        if not webhook_url:
            await interaction.followup.send("❌ PRIZES_WEBHOOK_URL не задан в .env", ephemeral=True)
            return

        session = getattr(self.bot, "http_session", None)
        if session is None or session.closed:
            await interaction.followup.send("❌ HTTP-сессия бота не готова. Перезапусти бота.", ephemeral=True)
            return

        try:
            webhook = discord.Webhook.from_url(webhook_url, session=session)
            await webhook.send(content=PRIZES_WEBHOOK_TEXT, wait=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Не удалось отправить webhook: {e}", ephemeral=True)
            return

        await interaction.followup.send("✅ Сообщение о призах отправлено в webhook.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
