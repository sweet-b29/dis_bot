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
    try:
        text = await resp.text()
    except aiohttp.ClientError as e:
        logger.warning(f"HTTP read error ({resp.status}): {e}")
        return {}
    try:
        return json.loads(text)
    except Exception as e:
        logger.error(f"❌ Ошибка JSON ({resp.status}): {e}; raw={text[:300]}")
        return {}

async def _request(method: str, url: str, **kwargs):
    """Возвращает ОТКРЫТЫЙ aiohttp.ClientResponse (caller читает и закрывает).
    Делает экспоненциальные ретраи на 429/5xx и сетевых ошибках.
    """
    retries = kwargs.pop("retries", 3)
    backoff = kwargs.pop("backoff", 0.5)

    async with get_session() as session:
        resp: aiohttp.ClientResponse | None = None
        for attempt in range(retries + 1):
            try:
                resp = await session.request(method, url, **kwargs)  # <= БЕЗ async with
                # ретраим тяжёлые статусы
                if resp.status == 429 or 500 <= resp.status < 600:
                    body = ""
                    try:
                        body = await resp.text()
                    except Exception:
                        pass
                    wait = resp.headers.get("Retry-After")
                    wait_s = float(wait) if wait else backoff * (2 ** attempt)
                    logger.warning(f"{method} {url} -> {resp.status}, retry in {wait_s:.2f}s; body={body[:160]}")
                    # освобождаем ответ перед следующей попыткой
                    resp.release()
                    if attempt < retries:
                        await asyncio.sleep(min(wait_s, 5.0))
                        continue
                return resp  # <-- Открытый resp; дальше его читает _safe_json()
            except aiohttp.ClientError as e:
                logger.warning(f"{method} {url} network error: {e}")
                if resp is not None:
                    resp.release()
                if attempt < retries:
                    await asyncio.sleep(backoff * (2 ** attempt))
                    continue
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
    try:
        resp = await _request("GET", api(f"players/{discord_id}/"), headers=HEADERS)
        if resp is None:
            # сети нет / соединение оборвалось — вернём "пусто", НЕ кидаем исключение
            return {}
        if resp.status == 404:
            return {}
        if resp.status != 200:
            logger.warning(f"GET players/{discord_id} -> {resp.status}")
            return {}
        return await _safe_json(resp)
    except Exception as e:
        # на всякий: ни одного исключения наружу
        logger.warning(f"get_player_profile({discord_id}) error: {e}")
        return {}


async def update_player_profile(discord_id: int, username: str | None = None, rank: str | None = None, create_if_not_exist: bool = False) -> dict:
    payload = {"discord_id": discord_id, "create_if_not_exist": create_if_not_exist}
    if username is not None:
        payload["username"] = username
    if rank is not None:
        payload["rank"] = rank

    try:
        resp = await _request("PATCH", api("players/update_profile/"), headers=HEADERS, json=payload)
        if resp is None:
            return {"error": "network error"}
        data = await _safe_json(resp)
        if resp.status not in (200, 201):
            logger.error(f"PATCH update_profile -> {resp.status}; body={data}")
            return {"error": "update_profile failed"}
        return data
    except Exception as e:
        logger.warning(f"update_player_profile error: {e}")
        return {"error": "network error"}


async def set_player_wins(discord_id: int, wins: int):
    payload = {"wins": wins}
    resp = await _request("POST", api(f"players/{discord_id}/set_wins/"), headers=HEADERS, json=payload)
    if resp is None:
        return {"error": "network error"}
    return await _safe_json(resp)

async def get_all_players():
    resp = await _request("GET", api("players/"), headers=HEADERS)
    if resp is None:
        return []
    return await _safe_json(resp)

async def add_win(discord_id: int):
    resp = await _request("POST", api(f"players/{discord_id}/add_win/"), headers=HEADERS)
    if resp is None:
        return {"error": "network error"}
    return await _safe_json(resp)

async def get_top10_players():
    resp = await _request("GET", api("players/top10/"), headers=HEADERS)
    if resp is None or resp.status != 200:
        return []
    return await _safe_json(resp)

# --- Matches ---

async def create_match(payload: dict):
    resp = await _request("POST", api("matches/"), headers=HEADERS, json=payload)
    if resp is None:
        logger.error("Ошибка при создании матча: сеть недоступна")
        return {}
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
    resp = await _request("GET", api("matches/"), headers=HEADERS)
    if resp is None:
        return []
    return await _safe_json(resp)

async def save_match_result(match_id: int, winner_team: int):
    payload = {"winner_team": winner_team}
    resp = await _request("POST", api(f"matches/{match_id}/set_winner/"), headers=HEADERS, json=payload)
    if resp is None:
        return {"error": "network error"}
    if resp.status != 200:
        logger.error(f"❌ Ошибка при сохранении результата матча: {resp.status} - {await resp.text()}")
    return await _safe_json(resp)

# --- Lobbies ---

async def create_lobby(data: dict):
    resp = await _request("POST", api("lobbies/"), headers=HEADERS, json=data)
    if resp is None:
        return {}
    if resp.status != 201:
        logger.warning(f"⚠ Не удалось создать лобби: {resp.status}")
        return {}
    return await _safe_json(resp)

async def update_lobby(lobby_id: int, data: dict):
    resp = await _request("PATCH", api(f"lobbies/{lobby_id}/"), headers=HEADERS, json=data)
    if resp is None:
        return {}
    if resp.status not in [200, 204]:
        logger.warning(f"⚠ Не удалось обновить лобби {lobby_id}: {resp.status}")
        return {}
    return await _safe_json(resp)

# --- Bans ---

async def is_banned(discord_id: int) -> dict:
    resp = await _request("GET", api("bans/is_banned/"), headers=HEADERS, params={"discord_id": discord_id})
    if resp is None:
        return {"banned": False}
    if resp.status != 200:
        return {"banned": False}
    return await _safe_json(resp)

async def ban_player(discord_id: int, expires_at: datetime, reason: str, banned_by_id: int | None = None) -> bool:
    # 1) получаем профиль (функция уже безопасная и не кидает исключения)
    profile = await get_player_profile(discord_id)
    player_id = profile.get("id")
    if not player_id:
        logger.warning(f"⛔ Игрок с Discord ID {discord_id} не найден — бан невозможен.")
        return False

    # 2) нормализуем время в UTC ISO8601
    expires_aware = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    expires_iso = expires_aware.astimezone(timezone.utc).isoformat()

    payload = {
        "player": player_id,
        "reason": reason,
        "expires_at": expires_iso,
    }
    # если на бэке есть поле — отправляем; если нет, можно оставить, оно будет проигнорировано
    if banned_by_id is not None:
        payload["banned_by"] = banned_by_id

    # 3) делаем запрос через _request (ВОЗВРАЩАЕТ ОТКРЫТЫЙ resp), НО БЕЗ async with
    resp = await _request("POST", api("bans/"), headers=HEADERS, json=payload)
    if resp is None:
        logger.error(f"❌ Сеть недоступна — бан {discord_id} не отправлен.")
        return False

    # 4) читаем тело и логируем, не падая на ошибках сети
    try:
        ok = resp.status in (200, 201)
        if ok:
            logger.success(f"✅ Бан успешно отправлен для {discord_id}")
            # можно прочитать ответ, если нужно:
            # _ = await _safe_json(resp)
            return True
        else:
            body = await resp.text()
            logger.error(f"❌ Не удалось выдать бан {discord_id}: {resp.status} - {body[:400]}")
            return False
    except Exception as e:
        logger.warning(f"⚠ Ошибка чтения ответа при бане {discord_id}: {e}")
        return False