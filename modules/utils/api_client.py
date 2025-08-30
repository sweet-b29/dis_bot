import aiohttp, asyncio, time
import os
from loguru import logger
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

API_BASE_URL = os.getenv("DJANGO_API_URL", "http://127.0.0.1:8000/api").rstrip("/")
DJANGO_API_TOKEN = os.getenv("DJANGO_API_TOKEN")
HEADERS = {"Authorization": f"Token {os.getenv('DJANGO_API_TOKEN')}"}
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=10, sock_read=10)

_session: aiohttp.ClientSession | None = None

def set_http_session(session: aiohttp.ClientSession):
    """Вызывается из main.py один раз при старте бота."""
    global _session
    _session = session

class _SessionCtx:
    """Вернёт общую сессию, а если её нет — создаст временную и сам закроет."""
    def __init__(self):
        self._owned = False
        self._tmp: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> aiohttp.ClientSession:
        if _session is not None:
            return _session
        self._owned = True
        self._tmp = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
        return self._tmp

    async def __aexit__(self, exc_type, exc, tb):
        if self._owned and self._tmp is not None:
            await self._tmp.close()

def get_session() -> _SessionCtx:
    return _SessionCtx()

async def _safe_json(resp: aiohttp.ClientResponse) -> dict:
    text = await resp.text()
    try:
        return json.loads(text)
    except Exception as e:
        logger.error(f"❌ Ошибка JSON ({resp.status}): {e}; raw={text[:300]}")
        return {}

async def _request(method: str, url: str, **kwargs):
    """Запрос с экспоненциальными ретраями на сетевые ошибки и 429/5xx."""
    retries = kwargs.pop("retries", 3)
    backoff = kwargs.pop("backoff", 0.5)
    async with get_session() as session:
        for attempt in range(retries + 1):
            try:
                async with session.request(method, url, **kwargs) as resp:
                    # ретраим тяжёлые статусы
                    if resp.status == 429 or 500 <= resp.status < 600:
                        body = await resp.text()
                        wait = resp.headers.get("Retry-After")
                        wait_s = float(wait) if wait else backoff * (2 ** attempt)
                        logger.warning(f"{method} {url} -> {resp.status}, retry in {wait_s:.2f}s; body={body[:160]}")
                        if attempt < retries:
                            await asyncio.sleep(min(wait_s, 5.0))
                            continue
                    return resp
            except aiohttp.ClientError as e:
                logger.warning(f"{method} {url} network error: {e}")
                if attempt < retries:
                    await asyncio.sleep(backoff * (2 ** attempt))
                    continue
                # последняя попытка провалилась — возвращаем None, но НЕ бросаем исключение
                return None

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
    return f"{API_BASE_URL}/{path.lstrip('/')}"

# --- Players ---

async def get_player_profile(discord_id: int) -> dict:
    resp = await _request("GET", api(f"players/{discord_id}/"), headers=HEADERS)
    if resp is None:
        # сеть упала/соединение закрыто — тихо возвращаем пусто
        return {}
    if resp.status == 404:
        return {}
    if resp.status != 200:
        logger.warning(f"GET players/{discord_id} -> {resp.status}")
        return {}
    return await _safe_json(resp)

async def update_player_profile(discord_id: int, username: str | None = None, rank: str | None = None, create_if_not_exist: bool = False) -> dict:
    payload = {
        "discord_id": discord_id,
        "create_if_not_exist": create_if_not_exist,
    }
    if username is not None:
        payload["username"] = username
    if rank is not None:
        payload["rank"] = rank

    resp = await _request("PATCH", api("players/update_profile/"), headers=HEADERS, json=payload)
    if resp is None:
        return {"error": "network error"}
    body = await _safe_json(resp)
    if resp.status not in (200, 201):
        logger.error(f"PATCH update_profile -> {resp.status}; body={body}")
        return {"error": "update_profile failed"}
    return body

async def set_player_wins(discord_id: int, wins: int):
    payload = {"wins": wins}
    async with await _request("POST", f"players/{discord_id}/set_wins/", json=payload) as resp:
        return await _safe_json(resp)

async def get_all_players():
    async with await _request("GET", "players/") as resp:
        return await _safe_json(resp)

async def add_win(discord_id: int):
    async with await _request("POST", f"players/{discord_id}/add_win/") as resp:
        return await _safe_json(resp)

async def get_top10_players():
    async with await _request("GET", "players/top10/") as resp:
        return await _safe_json(resp) if resp.status == 200 else []

# --- Matches ---

async def create_match(payload: dict):
    async with await _request("POST", "matches/", json=payload) as resp:
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
    async with await _request("GET", "matches/") as resp:
        return await _safe_json(resp)

async def save_match_result(match_id: int, winner_team: int):
    payload = {"winner_team": winner_team}
    async with await _request("POST", f"matches/{match_id}/set_winner/", json=payload) as resp:
        if resp.status != 200:
            logger.error(f"❌ Ошибка при сохранении результата матча: {resp.status} - {await resp.text()}")
        return await _safe_json(resp)

# --- Lobbies ---

async def create_lobby(data: dict):
    async with await _request("POST", "lobbies/", json=data) as resp:
        if resp.status != 201:
            logger.warning(f"⚠ Не удалось создать лобби: {resp.status}")
            return {}
        return await _safe_json(resp)

async def update_lobby(lobby_id: int, data: dict):
    async with await _request("PATCH", f"lobbies/{lobby_id}/", json=data) as resp:
        if resp.status not in [200, 204]:
            logger.warning(f"⚠ Не удалось обновить лобби {lobby_id}: {resp.status}")
            return {}
        try:
            return await _safe_json(resp)
        except:
            return {}

# --- Bans ---

async def is_banned(discord_id: int) -> dict:
    async with await _request("GET", "bans/is_banned/", params={"discord_id": discord_id}) as resp:
        return await _safe_json(resp) if resp.status == 200 else {"banned": False}

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

    async with await _request("POST", "bans/", json=payload) as resp:
        if resp.status in [200, 201]:
            logger.success(f"✅ Бан успешно отправлен для {discord_id}")
            return True
        else:
            error = await resp.text()
            logger.error(f"❌ Не удалось выдать бан {discord_id}: {resp.status} - {error}")
            return False