import io
from loguru import logger
import discord
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import os

async def move_members(voice_channel: discord.VoiceChannel, members: list):
    """Перемещает указанных игроков в голосовой канал."""
    if not voice_channel:
        logger.error("❌ Ошибка: Голосовой канал не найден.")
        return

    for member in members:
        if not member.voice:
            logger.warning(f"⚠ {member.name} не в голосовом канале, пропускаем.")
            continue

        try:
            await member.move_to(voice_channel)
            logger.info(f"✅ {member.name} перемещён в {voice_channel.name}.")
        except discord.Forbidden:
            logger.error(f"❌ Бот не имеет прав на перемещение {member.name}.")
        except discord.HTTPException as e:
            logger.error(f"❌ Ошибка при перемещении {member.name}: {e}")

def log_action(user: discord.Member, action: str):
    """Логирует действия пользователя."""
    logger.info(f"[Действие] {user.display_name}: {action}")


def get_channel_by_name(guild: discord.Guild, name: str):
    """Возвращает канал по имени."""
    return discord.utils.get(guild.channels, name=name)

def create_discord_file(image_path: str, filename: str = "lobby_dynamic.png") -> discord.File:
    with open(image_path, "rb") as f:
        buffer = io.BytesIO(f.read())
        buffer.seek(0)
        return discord.File(fp=buffer, filename=filename)

def humanize_timedelta(td: timedelta) -> str:
    total = max(int(td.total_seconds()), 0)
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d: parts.append(f"{d}д")
    if h: parts.append(f"{h}ч")
    if m or not parts: parts.append(f"{m}м")
    return " ".join(parts)

def render_ban_message(expires_at_iso: str, reason: str | None = None) -> str:
    """
    Превращает ISO-время бана из API в читабельный текст с локальным временем,
    UTC и строкой «Осталось: ...».
    """
    # robust парсинг ISO (поддержим 'Z')
    try:
        exp_utc = datetime.fromisoformat(expires_at_iso.replace("Z", "+00:00"))
        if exp_utc.tzinfo is None:
            exp_utc = exp_utc.replace(tzinfo=timezone.utc)
        else:
            exp_utc = exp_utc.astimezone(timezone.utc)
    except Exception:
        return "🚫 Вы забанены. Не удалось распарсить дату окончания. Обратитесь к админам."

    tz_name = os.getenv("BOT_TZ", "Asia/Almaty")
    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = ZoneInfo("UTC")
        tz_name = "UTC"

    now_utc = datetime.now(timezone.utc)
    left_str = humanize_timedelta(exp_utc - now_utc)

    local_dt = exp_utc.astimezone(local_tz)
    offset_hours = int(local_dt.utcoffset().total_seconds() // 3600)
    sign = "+" if offset_hours >= 0 else "-"
    offset_fmt = f"UTC{sign}{abs(offset_hours)}"

    utc_str = exp_utc.strftime("%Y-%m-%d %H:%M UTC")
    local_str = local_dt.strftime("%Y-%m-%d %H:%M")

    reason_text = reason or "—"
    return (
        f"🚫 Вы забанены до **{local_str}** (*{tz_name}, {offset_fmt}*). "
        f"Осталось: **{left_str}**.\n"
        f"🕒 UTC: {utc_str}\n"
        f"📝 Причина: **{reason_text}**"
    )
