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
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS lobbies (
                    lobby_id SERIAL PRIMARY KEY,
                    channel_id BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP,
                    captain_1_id BIGINT,
                    captain_2_id BIGINT,
                    team_1 TEXT,
                    team_2 TEXT,
                    winner_team INT
                );
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
                SELECT r.user_id, r.wins, p.username
                FROM ratings r
                LEFT JOIN player_profiles p ON r.user_id = p.user_id
                ORDER BY r.wins DESC
                LIMIT 10;
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

async def save_lobby(channel_id: int, captain_1_id: int, captain_2_id: int):
    query = """
        INSERT INTO lobbies (channel_id, captain_1_id, captain_2_id)
        VALUES ($1, $2, $3)
        RETURNING lobby_id;
    """
    row = await db_pool.fetchrow(query, channel_id, captain_1_id, captain_2_id)
    return row['lobby_id']

async def set_wins(user_id: int, wins: int):
    await db_pool.execute("""
        INSERT INTO ratings (user_id, wins)
        VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET wins = EXCLUDED.wins
    """, user_id, wins)


async def get_all_profiles_with_wins():
    return await db_pool.fetch("""
        SELECT p.user_id, p.username, p.rank, COALESCE(r.wins, 0) AS wins
        FROM player_profiles p
        LEFT JOIN ratings r ON p.user_id = r.user_id
        ORDER BY wins DESC
    """)


async def update_lobby(lobby_id: int, team_1: list[int], team_2: list[int], winner_team: int = None):
    query = """
        UPDATE lobbies
        SET closed_at = NOW(),
            team_1 = $1,
            team_2 = $2,
            winner_team = $3
        WHERE lobby_id = $4;
    """
    await db_pool.execute(query, ",".join(map(str, team_1)), ",".join(map(str, team_2)), winner_team, lobby_id)


