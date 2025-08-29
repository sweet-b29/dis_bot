import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from pathlib import Path
import logging
from loguru import logger
from modules.lobby.lobby import LobbyMenuView
from discord import File
from modules.utils.api_client import ensure_api_config
import aiohttp
from modules.utils import api_client

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", 0))
LOBBY_CHANNEL_ID = int(os.getenv("LOBBY_CHANNEL_ID", 0))

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents)

def ensure_bot_env():
    missing = []
    if not os.getenv("DISCORD_BOT_TOKEN"):
        missing.append("DISCORD_BOT_TOKEN")
    if not os.getenv("GUILD_ID"):
        missing.append("GUILD_ID")
    if not os.getenv("LOBBY_CHANNEL_ID"):
        missing.append("LOBBY_CHANNEL_ID")
    if not os.getenv("BOT_TZ"):
        logger.warning("BOT_TZ не задан — по умолчанию будет Asia/Almaty")
    if missing:
        raise RuntimeError(f"ENV ошибки: отсутствуют {', '.join(missing)}")

@bot.event
async def on_ready():
    logger.success(f"🤖 Бот {bot.user} запущен и готов к работе!")


@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel and before.channel != after.channel:
        vc = before.channel

        # Проверка: канал пуст или нет
        if len(vc.members) == 0 and any(vc.name.startswith(prefix) for prefix in ("♦", "♣")):
            try:
                await vc.delete(reason="Все участники покинули канал.")
                logger.info(f"🗑 Голосовой канал автоматически удалён: {vc.name}")
            except Exception as e:
                logger.warning(f"❌ Не удалось удалить голосовой канал {vc.name}: {e}")


@bot.event
async def setup_hook():
    # Загрузка всех команд из modules/commands/*
    base_dir = Path(__file__).resolve().parents[2]
    commands_dir = base_dir / "modules" / "commands"

    for path in commands_dir.glob("*.py"):
        if path.name.startswith("_"):
            continue
        ext = f"modules.commands.{path.stem}"
        try:
            await bot.load_extension(ext)
            logger.success(f"✅ Загрузили команду: {ext}")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки {ext}: {e}")

    timeout = aiohttp.ClientTimeout(total=10, connect=5, sock_read=10)
    bot.http_session = aiohttp.ClientSession(timeout=timeout)
    api_client.set_http_session(bot.http_session)

    # Синхронизация команд на сервере
    try:
        guild = discord.Object(id=GUILD_ID)
        await bot.tree.sync(guild=guild)
        logger.success(f"✅ Slash-команды синхронизированы (guild={GUILD_ID})")
    except Exception as e:
        logger.error(f"❌ Ошибка синхронизации команд: {e}")

    # Отправка кнопки "Создать лобби" в канал при запуске
    if LOBBY_CHANNEL_ID:
        try:
            channel = await bot.fetch_channel(LOBBY_CHANNEL_ID)
            if channel:
                file_path = base_dir / "modules" / "pictures" / "Создание лобби.jpg"
                file = File(fp=file_path, filename="создание_лобби.jpg")
                view = LobbyMenuView(bot)
                await channel.send(file=file, view=view)
                logger.success("📨 Отправлена кнопка создания лобби.")
        except Exception as e:
            logger.warning(f"⚠ Ошибка при отправке кнопки лобби: {e}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    try:
        await interaction.response.send_message("❌ Что-то пошло не так. Мы уже смотрим логи.", ephemeral=True)
    except discord.InteractionResponded:
        await interaction.followup.send("❌ Что-то пошло не так. Мы уже смотрим логи.", ephemeral=True)
    logger.exception(f"App command error: {error}")

if __name__ == "__main__":
    ensure_api_config()
    ensure_bot_env()
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    bot.run(TOKEN)
