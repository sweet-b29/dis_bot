import os
import sys
import time
import logging
from pathlib import Path

from dotenv import load_dotenv

# ВАЖНО:
# .env должен загрузиться ДО импортов внутренних модулей проекта,
# потому что api_client / valorant_api / lobby могут читать env на уровне импорта.
BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=BASE_DIR / ".env")

import aiohttp
import discord
from discord import File, HTTPException, InteractionResponded
from discord.ext import commands, tasks
from loguru import logger

from modules.lobby.lobby import LobbyMenuView
from modules.utils import api_client, valorant_api
from modules.utils.api_client import ensure_api_config

def get_env_int(name: str, default: int = 0) -> int:
    raw = os.getenv(name)

    if raw is None or str(raw).strip() == "":
        return default

    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"ENV ошибка: {name} должен быть числом, сейчас: {raw!r}")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = get_env_int("GUILD_ID")
LOBBY_CHANNEL_ID = get_env_int("LOBBY_CHANNEL_ID")
LOBBY_PANEL_MESSAGE_ID = get_env_int("LOBBY_PANEL_MESSAGE_ID")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.voice_states = True
intents.message_content = False

bot = commands.Bot(command_prefix=".", intents=intents)
bot.lobby_panel_message = None

def ensure_bot_env():
    missing = []
    if not os.getenv("DISCORD_BOT_TOKEN"):
        missing.append("DISCORD_BOT_TOKEN")
    if not os.getenv("GUILD_ID"):
        missing.append("GUILD_ID")
    if not os.getenv("LOBBY_CHANNEL_ID"):
        missing.append("LOBBY_CHANNEL_ID")
    if not os.getenv("HENRIKDEV_API_KEY"):
        missing.append("HENRIKDEV_API_KEY")
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

@tasks.loop(minutes=1)
async def refresh_lobby_panel_view():
    message = getattr(bot, "lobby_panel_message", None)
    if not message:
        return

    try:
        await message.edit(view=LobbyMenuView(bot))
    except Exception as e:
        logger.warning(f"⚠ Не удалось обновить панель лобби: {e}")

@bot.event
async def setup_hook():
    # Загрузка всех команд из modules/commands/*
    base_dir = Path(__file__).resolve().parents[2]
    commands_dir = base_dir / "modules" / "commands"

    for path in commands_dir.glob("*.py"):
        if path.name.startswith("_") or path.name == "__init__.py":
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
    valorant_api.set_http_session(bot.http_session)

    _original_close = bot.close

    async def _close_with_http():
        try:
            if refresh_lobby_panel_view.is_running():
                refresh_lobby_panel_view.cancel()

            if hasattr(api_client, "close_http_session"):
                await api_client.close_http_session()
            if hasattr(valorant_api, "close_http_session"):
                await valorant_api.close_http_session()
            if hasattr(bot, "http_session") and bot.http_session and not bot.http_session.closed:
                await bot.http_session.close()
        finally:
            await _original_close()

    bot.close = _close_with_http

    # Синхронизация slash-команд в конкретную гильдию (быстро появляется в Discord)
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        logger.success(f"✅ Slash-команды синхронизированы в guild={GUILD_ID}. Всего: {len(synced)}")
    except Exception as e:
        logger.error(f"❌ Ошибка синхронизации команд: {e}")

    # Отправка/восстановление панели "Создать лобби"
    if LOBBY_CHANNEL_ID:
        try:
            channel = await bot.fetch_channel(LOBBY_CHANNEL_ID)

            if channel:
                view = LobbyMenuView(bot)
                restored = False

                # Если известен ID старого сообщения — пробуем восстановить панель
                if LOBBY_PANEL_MESSAGE_ID:
                    try:
                        message = await channel.fetch_message(LOBBY_PANEL_MESSAGE_ID)
                        await message.edit(view=view)
                        bot.lobby_panel_message = message
                        restored = True
                        logger.success(f"♻️ Восстановлена старая панель лобби: {LOBBY_PANEL_MESSAGE_ID}")
                    except Exception as e:
                        logger.warning(f"⚠ Не удалось восстановить старую панель лобби: {e}")

                # Если старую панель не нашли — создаём новую
                if not restored:
                    file_path = BASE_DIR / "modules" / "pictures" / "Создание лобби.png"

                    if not file_path.exists():
                        logger.warning(f"⚠ Картинка панели лобби не найдена: {file_path}")
                    else:
                        file = File(fp=file_path, filename="создание_лобби.jpg")
                        bot.lobby_panel_message = await channel.send(file=file, view=view)

                        logger.success(
                            "📨 Отправлена новая кнопка создания лобби. "
                            f"ID сообщения: {bot.lobby_panel_message.id}. "
                            "Добавь его в .env как LOBBY_PANEL_MESSAGE_ID, чтобы не создавать дубли."
                        )

                if bot.lobby_panel_message and not refresh_lobby_panel_view.is_running():
                    refresh_lobby_panel_view.start()

        except Exception as e:
            logger.warning(f"⚠ Ошибка при отправке/восстановлении кнопки лобби: {e}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    """
    Универсальный хэндлер ошибок slash-команд.
    Не пытается второй раз отвечать на уже обработанный interaction
    и игнорирует ошибки протухшего webhook-токена.
    """
    try:
        if interaction.response.is_done():
            # Уже был ответ / defer — шлём followup, если токен ещё жив
            await interaction.followup.send(
                "❌ Что-то пошло не так. Мы уже смотрим логи.",
                ephemeral=True,
            )
        else:
            # Ещё не отвечали по этому interaction
            await interaction.response.send_message(
                "❌ Что-то пошло не так. Мы уже смотрим логи.",
                ephemeral=True,
            )
    except (InteractionResponded, HTTPException):
        # Ответ уже был, либо webhook-токен протух — просто логируем.
        pass

    logger.exception(f"App command error: {error}")

if __name__ == "__main__":
    ensure_api_config()
    ensure_bot_env()
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)

    try:
        bot.run(TOKEN)
    except HTTPException as e:
        # Если это именно 429 на логине — не переиспользуем текущий объект бота,
        # а перезапускаем процесс, чтобы подняться с «чистой» Discord session.
        if getattr(e, "status", None) == 429:
            logger.error("⚠ Discord вернул 429 Too Many Requests при логине. Ждём 60 секунд и перезапускаем процесс.")
            time.sleep(60)
            os.execv(sys.executable, [sys.executable, *sys.argv])

        # Любая другая ошибка – пусть падает, чтобы мы увидели реальную проблему
        raise
