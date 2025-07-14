from loguru import logger
import discord
from discord.ext import commands


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
