import os
import logging
import discord
from discord.ext import commands
from modules import lobby, draft, database
from loguru import logger
from modules.lobby import CreateLobbyButton
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='.',intents=intents)

@bot.event
async def on_ready():
    if not hasattr(bot, 'lobby_counter'):
        bot.lobby_counter = 0
    logger.success(f"Бот {bot.user} успешно запущен.")

    channel_id = int(os.getenv("LOBBY_CHANNEL_ID"))
    channel = bot.get_channel(channel_id)

    if channel:
        embed = discord.Embed(
            title="🎮 Добро пожаловать в кастом-лобби!",
            description=(
                "Нажмите на кнопку ниже, чтобы **создать лобби** для дружеской игры.\n\n"
                "📌 **Максимум игроков**: `10`\n"
                "⚔️ После сбора — автоматический **драфт капитанов**, **распределение команд** и **создание голосовых каналов**.\n\n"
                "🕹 Будь готов к весёлой игре!"
            ),
            color=discord.Color.blue()
        )
        embed.set_footer(text="Создатель лобби автоматически становится организатором.")

        view = CreateLobbyButton(bot)
        await channel.send(embed=embed, view=view)
    else:
        logger.error("⚠️ Не найден канал с указанным ID.")


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


logging.getLogger("discord.gateway").setLevel(logging.WARNING)


# Проверяем наличие токена перед запуском
if not TOKEN:
    logger.error("❌ DISCORD_BOT_TOKEN не найден в .env")
    exit(1)

if not DATABASE_URL:
    logger.warning("⚠ DATABASE_URL не указан. Бот будет работать без БД.")

# Настройка модулей
lobby.setup(bot)
draft.setup(bot)

# Запуск бота
try:
    @bot.event
    async def setup_hook():
        # Инициализация БД до загрузки команд
        try:
            try:
                await database.create_db_pool(bot, DATABASE_URL)
                logger.success("✅ Подключение к базе данных установлено.")
            except Exception as e:
                logger.warning(f"⚠ База данных недоступна, продолжаем без неё: {e}")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к БД: {e}")
            await bot.close()
            return

        # Загрузка модулей
        await bot.load_extension("modules.rating")
        await bot.load_extension("modules.admin")
        await bot.load_extension("modules.profile")
        await bot.tree.sync()
        logger.success("✅ Slash-команды синхронизированы с Discord API.")

    bot.run(TOKEN)

except discord.LoginFailure:
    logger.error("❌ Неверный токен Discord.")
except Exception as e:
    logger.error(f"❌ Фатальная ошибка: {e}")
