import aiohttp
import os
from loguru import logger
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

API_BASE_URL = os.getenv("DJANGO_API_URL", "http://127.0.0.1:8000/api").rstrip("/")
DJANGO_API_TOKEN = os.getenv("DJANGO_API_TOKEN")

HEADERS = {
    "Authorization": f"Token {DJANGO_API_TOKEN}",
}

def ensure_api_config():
    missing = []
    if not API_BASE_URL:
        missing.append("DJANGO_API_URL")
    if not DJANGO_API_TOKEN:
        missing.append("DJANGO_API_TOKEN")
    if missing:
        from loguru import logger
        raise RuntimeError(f"ENV ошибки: отсутствуют {', '.join(missing)}. "
                           f"Проверь .env и перезапусти бота.")

def api(path: str) -> str:
    # корректно склеиваем, чтобы слеши не «дублились»
    return f"{API_BASE_URL}/{path.lstrip('/')}"

# Вспомогательная функция для сессий с токеном
def get_session():
    timeout = aiohttp.ClientTimeout(total=10, connect=5, sock_read=10)
    return aiohttp.ClientSession(headers=HEADERS, timeout=timeout)

# --- Players ---

async def get_player_profile(discord_id: int):
    async with get_session() as session:
        async with session.get(api(f"players/{discord_id}/")) as resp:
            if resp.status == 404:
                return {}  # тишина, профиля просто нет
            if resp.status != 200:
                logger.error(f"❌ Не удалось получить профиль {discord_id}: статус {resp.status}, тело={await resp.text()}")
                return {}
            try:
                return await resp.json()
            except Exception as e:
                logger.error(f"❌ Ошибка JSON профиля {discord_id}: {e}")
                return {}

async def update_player_profile(
    discord_id: int,
    username: str | None = None,
    rank: str | None = None,
    create_if_not_exist: bool = False,
):
    # формируем payload БЕЗ None-полей
    payload = {"discord_id": discord_id, "create_if_not_exist": create_if_not_exist}
    if username is not None:
        payload["username"] = username
    if rank is not None:
        payload["rank"] = rank

    async with get_session() as session:
        async with session.patch(api("players/update_profile/"), json=payload) as resp:
            body = await resp.text()
            if resp.status not in (200, 201):
                logger.error(f"❌ update_profile {resp.status}: {body[:400]}")
                raise RuntimeError(f"update_profile failed: {resp.status}")
            try:
                return await resp.json()
            except Exception:
                logger.error("❌ Некорректный JSON от update_profile")
                return {}

async def set_player_wins(discord_id: int, wins: int):
    payload = {"wins": wins}
    async with get_session() as session:
        async with session.post(api(f"players/{discord_id}/set_wins/"), json=payload) as resp:
            return await resp.json()

async def get_all_players():
    async with get_session() as session:
        async with session.get(api("players/")) as resp:
            return await resp.json()

async def add_win(discord_id: int):
    async with get_session() as session:
        async with session.post(api(f"players/{discord_id}/add_win/")) as resp:
            return await resp.json()

async def get_top10_players():
    async with get_session() as session:
        async with session.get(api("players/top10/")) as resp:
            return await resp.json() if resp.status == 200 else []

# --- Matches ---

async def create_match(payload: dict):
    async with get_session() as session:
        async with session.post(api("matches/"), json=payload) as resp:
            text = await resp.text()
            if resp.status != 201:
                logger.error(f"Ошибка при создании матча: {resp.status} - {text}")
            else:
                logger.success(f"Матч успешно создан: {text}")
            try:
                return json.loads(text)
            except Exception as e:
                logger.error(f"❌ Ошибка при разборе JSON: {e}")
                return {}

async def get_all_matches():
    async with get_session() as session:
        async with session.get(api("matches/")) as resp:
            return await resp.json()

async def save_match_result(match_id: int, winner_team: int):
    payload = {"winner_team": winner_team}
    async with get_session() as session:
        async with session.post(api(f"matches/{match_id}/set_winner/"), json=payload) as resp:
            if resp.status != 200:
                logger.error(f"❌ Ошибка при сохранении результата матча: {resp.status} - {await resp.text()}")
            return await resp.json()

# --- Lobbies ---

async def create_lobby(data: dict):
    async with get_session() as session:
        async with session.post(api("lobbies/"), json=data) as resp:
            if resp.status != 201:
                logger.warning(f"⚠ Не удалось создать лобби: {resp.status}")
                return {}
            return await resp.json()

async def update_lobby(lobby_id: int, data: dict):
    async with get_session() as session:
        async with session.patch(api(f"lobbies/{lobby_id}/"), json=data) as resp:
            if resp.status not in [200, 204]:
                logger.warning(f"⚠ Не удалось обновить лобби {lobby_id}: {resp.status}")
                return {}
            try:
                return await resp.json()
            except:
                return {}

# --- Bans ---

async def is_banned(discord_id: int) -> dict:
    async with get_session() as session:
        async with session.get(api("bans/is_banned/"), params={"discord_id": discord_id}) as resp:
            return await resp.json() if resp.status == 200 else {"banned": False}

async def ban_player(discord_id: int, expires_at: datetime, reason: str, banned_by_id: int = None):
    profile = await get_player_profile(discord_id)
    player_id = profile.get("id")

    if not player_id:
        logger.warning(f"⛔ Игрок с Discord ID {discord_id} не найден — бан невозможен.")
        return False

    expires_aware = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    expires_iso = expires_aware.astimezone(timezone.utc).isoformat()

    payload = {
        "player": player_id,
        "reason": reason,
        "expires_at": expires_iso
    }

    async with get_session() as session:
        async with session.post(api("bans/"), json=payload) as resp:
            if resp.status in [200, 201]:
                logger.success(f"✅ Бан успешно отправлен для {discord_id}")
                return True
            else:
                error = await resp.text()
                logger.error(f"❌ Не удалось выдать бан {discord_id}: {resp.status} - {error}")
                return False