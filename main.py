import discord, os
from discord.ext import commands
from modules import lobby, draft, rating, database
from loguru import logger
from modules.lobby import CreateLobbyButton
# from modules import modal

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")


intents = discord.Intents.all()
bot = commands.Bot(command_prefix='.', intents=intents)

@bot.event
async def on_ready():
    if not hasattr(bot, 'lobby_counter'):
        bot.lobby_counter = 0
    logger.success(f"Бот {bot.user} успешно запущен.")

    channel_id = 1353767233070956564
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

    try:
        await database.create_db_pool(bot, DATABASE_URL)
        await database.init_db()
        logger.success("✅ Подключение к базе данных установлено.")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к БД: {e}")
        await bot.close()
@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel and len(before.channel.members) == 0:
        if before.channel.name.startswith("♦︎") or before.channel.name.startswith("♣︎"):
            try:
                await before.channel.delete(reason="Все участники покинули канал.")
                logger.info(f"🗑 Голосовой канал удалён: {before.channel.name}")
            except Exception as e:
                logger.warning(f"⚠ Ошибка при удалении голосового канала: {e}")


@bot.command(name='delete_empty_vc')
@commands.has_permissions(manage_channels=True)
async def delete_empty_vc(ctx):
    deleted_channels = []
    for vc in ctx.guild.voice_channels:
        if any(tag in vc.name for tag in ("♦", "♣", "Команда")) and len(vc.members) == 0:
            try:
                await vc.delete(reason="Ручная очистка пустых голосовых каналов")
                deleted_channels.append(vc.name)
            except Exception as e:
                await ctx.send(f"❌ Ошибка при удалении {vc.name}: {e}")



# Проверяем наличие токена перед запуском
if not TOKEN:
    raise ValueError("❌ Ошибка: DISCORD_BOT_TOKEN не найден.")

# Настройка модулей
lobby.setup(bot)
draft.setup(bot)
rating.setup(bot)

# Запуск бота
try:
    bot.run(TOKEN)
except discord.LoginFailure:
    logger.error("❌ Неверный токен Discord. Проверьте .env файл.")
except Exception as e:
    logger.error(f"❌ Ошибка при запуске бота: {e}")
