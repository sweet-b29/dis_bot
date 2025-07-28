import aiohttp
import os
from loguru import logger
import json
from datetime import datetime

API_BASE_URL = os.getenv("DJANGO_API_URL", "http://127.0.0.1:8000/api")

# --- Players ---

async def get_player_profile(discord_id: int):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/players/{discord_id}/") as resp:
            if resp.status != 200:
                logger.warning(f"⚠ Не удалось получить профиль {discord_id}: статус {resp.status}")
                return {}

            try:
                data = await resp.json()
            except Exception as e:
                logger.error(f"❌ Ошибка при разборе JSON профиля {discord_id}: {e}")
                return {}

            # Дополнительно можно валидировать поля
            if not isinstance(data, dict):
                return {}

            return data


async def update_player_profile(discord_id: int, username: str = None, rank: str = None, create_if_not_exist: bool = False):
    payload = {
        "discord_id": discord_id,
        "username": username,
        "rank": rank,
        "create_if_not_exist": str(create_if_not_exist).lower()
    }

    async with aiohttp.ClientSession() as session:
        async with session.patch(
            f"{API_BASE_URL}/players/update_profile/",
            json=payload
        ) as resp:
            logger.warning(f"📤 Ответ от update_profile: статус={resp.status}, тело={await resp.text()}")
            try:
                return await resp.json()
            except Exception as e:
                logger.error(f"❌ Ошибка при разборе JSON: {e}")
                return {}




async def set_player_wins(discord_id: int, wins: int):
    payload = {"wins": wins}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_BASE_URL}/players/{discord_id}/set_wins/", json=payload) as resp:
            return await resp.json()


async def get_all_players():
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/players/") as resp:
            return await resp.json()


async def add_win(discord_id: int):
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_BASE_URL}/players/{discord_id}/add_win/") as resp:
            return await resp.json()


async def get_top10_players():
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/players/top10/") as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                return []


# --- Matches ---

async def create_match(payload: dict):
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_BASE_URL}/matches/", json=payload) as resp:
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
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/matches/") as resp:
            return await resp.json()


async def save_match_result(match_id: int, winner_team: int):
    payload = {"winner_team": winner_team}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_BASE_URL}/matches/{match_id}/set_winner/", json=payload) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error(f"❌ Ошибка при сохранении результата матча: {resp.status} - {error_text}")
            return await resp.json()

# --- Lobbies (если вернём логику создания лобби через Django позже) ---

async def create_lobby(data: dict):
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_BASE_URL}/lobbies/", json=data) as resp:
            if resp.status != 201:
                logger.warning(f"⚠ Не удалось создать лобби: {resp.status}")
                return {}
            return await resp.json()


async def update_lobby(lobby_id: int, data: dict):
    async with aiohttp.ClientSession() as session:
        async with session.patch(f"{API_BASE_URL}/lobbies/{lobby_id}/", json=data) as resp:
            if resp.status not in [200, 204]:
                logger.warning(f"⚠ Не удалось обновить лобби {lobby_id}: {resp.status}")
                return {}
            try:
                return await resp.json()
            except:
                return {}


async def is_banned(discord_id: int) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_BASE_URL}/bans/is_banned/", params={"discord_id": discord_id}) as resp:
            if resp.status == 200:
                return await resp.json()
            return {"banned": False}


async def ban_player(discord_id: int, expires_at: datetime, reason: str, banned_by_id: int = None):
    profile = await get_player_profile(discord_id)
    player_id = profile.get("id")

    if not player_id:
        logger.warning(f"⛔ Игрок с Discord ID {discord_id} не найден — бан невозможен.")
        return False

    payload = {
        "player": player_id,
        "reason": reason,
        "expires_at": expires_at.isoformat(),
        "banned_by": banned_by_id
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_BASE_URL}/bans/", json=payload) as resp:
            if resp.status in [200, 201]:
                logger.success(f"✅ Бан успешно отправлен для {discord_id}")
                return True
            else:
                error = await resp.text()
                logger.error(f"❌ Не удалось выдать бан {discord_id}: {resp.status} - {error}")
                return False