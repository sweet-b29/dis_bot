import asyncpg
from loguru import logger

db_pool = None

async def create_db_pool(bot, database_url):
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(database_url)
        await init_db()
        logger.success("✅ Подключение к БД установлено.")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к БД: {e}")
        db_pool = None

async def init_db():
    global db_pool
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ratings (
                    user_id BIGINT PRIMARY KEY,
                    wins INTEGER DEFAULT 0
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS player_profiles (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT NOT NULL,
                    rank TEXT NOT NULL
                )
            """)

        logger.success("✅ База данных инициализирована.")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

async def add_win(user_id: int):
    global db_pool
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO ratings(user_id, wins) VALUES($1, 1)
                ON CONFLICT (user_id) DO UPDATE SET wins = ratings.wins + 1
                RETURNING wins;
            """, user_id)
        logger.info(f"✅ Победа добавлена пользователю {user_id}. Всего побед: {row['wins']}")
        return row["wins"]
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении побед: {e}")
        return None

async def get_top10():
    global db_pool
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id, wins FROM ratings
                ORDER BY wins DESC LIMIT 10;
            """)
        return rows
    except Exception as e:
        logger.error(f"❌ Ошибка при получении топ-10 игроков: {e}")
        return []

async def execute_query(query, *args):
    global db_pool
    async with db_pool.acquire() as connection:
        await connection.execute(query, *args)

async def save_player_profile(user_id: int, username: str, rank: str):
    query = """
    INSERT INTO player_profiles (user_id, username, rank)
    VALUES ($1, $2, $3)
    ON CONFLICT (user_id) DO UPDATE
    SET username = EXCLUDED.username,
        rank = EXCLUDED.rank
    """
    await db_pool.execute(query, user_id, username, rank)

async def get_player_profile(user_id: int):
    query = "SELECT username, rank FROM player_profiles WHERE user_id = $1"
    return await db_pool.fetchrow(query, user_id)



# async def get_game_nickname(user_id: int):
#     query = "SELECT game_nickname FROM players WHERE user_id = $1"
#     return await db_pool.fetchval(query, user_id)
#
# async def save_game_nickname(user_id: int, nickname: str):
#     query = """
#         INSERT INTO players (user_id, game_nickname)
#         VALUES ($1, $2)
#         ON CONFLICT (user_id) DO UPDATE SET game_nickname = EXCLUDED.game_nickname
#     """
#     await db_pool.execute(query, user_id, nickname)

