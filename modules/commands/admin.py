import asyncio
import os
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from modules.utils.rank_sync import ensure_fresh_rank
from modules.utils import api_client
from modules.utils.valorant_api import ValorantRankError


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

    @app_commands.command(name="syncallranks", description="Синхронизировать ранги всех игроков через HenrikDev")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_all_ranks(self, interaction: discord.Interaction):
        """
        Медленный, но гарантированный синк:
        - идём по игрокам ПО ОЧЕРЕДИ (без gather, без параллелизма)
        - внутри ensure_fresh_rank уже есть rate-limit HenrikDev
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            players = await api_client.get_all_players()
        except Exception as e:
            await interaction.followup.send(f"❌ Не удалось получить список игроков: {e}", ephemeral=True)
            return

        if not players:
            await interaction.followup.send("⚠️ В базе нет игроков.", ephemeral=True)
            return

        total = len(players)
        updated = 0
        skipped_no_riot = 0
        errors = 0

        for idx, p in enumerate(players, start=1):
            discord_id = p.get("discord_id")
            username = p.get("username")

            if not discord_id:
                skipped_no_riot += 1
                continue

            # можно с кастомным Riot ID, если он есть
            riot_id = (username or "").strip()

            if not riot_id:
                skipped_no_riot += 1
                continue

            try:
                changed = await ensure_fresh_rank(
                    discord_id=int(discord_id),
                    username=riot_id,
                    force=True,
                    allow_unranked_overwrite=True,
                    return_updated_only=True,
                    raise_on_fetch_error=True,
                )
                if changed:
                    updated += 1

            except ValorantRankError as e:
                msg = str(e).lower()
                # если словили лимит 429 — сразу останавливаемся
                if "429" in msg or "лимит" in msg or "rate limit" in msg:
                    await interaction.followup.send(
                        f"⚠️ Остановлено из-за лимита HenrikDev (429).\n"
                        f"Всего игроков: {total}\n"
                        f"Успешно обновлено: {updated}\n"
                        f"Без Riot ID: {skipped_no_riot}\n"
                        f"Ошибок (кроме лимита): {errors}",
                        ephemeral=True,
                    )
                    return
                errors += 1
                continue

            except Exception:
                errors += 1
                continue

            # чуть отдаём управление циклу событий, чтобы бот не зависал
            await asyncio.sleep(0)

        await interaction.followup.send(
            f"✅ Синхронизация завершена.\n"
            f"Всего игроков: {total}\n"
            f"Обновлено рангов: {updated}\n"
            f"Без Riot ID: {skipped_no_riot}\n"
            f"Ошибок: {errors}",
            ephemeral=True,
        )


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
    @app_commands.describe(user="Имя игрока", duration="Длительность: 10m/2h/1d", reason="Причина")
    @admin_only()
    async def ban(self, interaction: discord.Interaction, user: discord.Member, duration: str, reason: str = "No reason"):
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
                discord_id=int(user.id),
                expires_at=expires_at,
                reason=reason,
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка при бане: {e}", ephemeral=True)
            return

        if ok:
            await interaction.followup.send(
                f"🔐 Бан выдан: **{user.id}**\n"
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
        embed.add_field(name="/changewins", value="Установить победы игрока", inline=False)
        embed.add_field(name="/ban", value="Бан по discord_id на время", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
