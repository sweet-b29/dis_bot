import os
import time
import asyncio
from urllib.parse import quote
from typing import Any

import aiohttp
from loguru import logger

HENRIKDEV_BASE_URL = os.getenv("HENRIKDEV_BASE_URL", "https://api.henrikdev.xyz").rstrip("/")
HENRIKDEV_API_KEY = os.getenv("HENRIKDEV_API_KEY", "").strip()

# HenrikDev STANDARD: 30 req/min. Берём запас, чтобы не ловить 429.
HENRIKDEV_RPM = float(os.getenv("HENRIKDEV_RPM", "25"))
HENRIKDEV_MAX_RETRIES = int(os.getenv("HENRIKDEV_MAX_RETRIES", "8"))

VALORANT_DEFAULT_REGION = os.getenv("VALORANT_DEFAULT_REGION", "eu").strip().lower()
VALORANT_PLATFORM = os.getenv("VALORANT_PLATFORM", "pc").strip().lower()
VALORANT_RANK_CACHE_TTL = float(os.getenv("VALORANT_RANK_CACHE_TTL", "3600"))  # seconds

# Регион почти не меняется — можно кэшировать надолго
VALORANT_REGION_CACHE_TTL = float(os.getenv("VALORANT_REGION_CACHE_TTL", "86400"))  # seconds

# Важно: это та же aiohttp-сессия, что и у бота (чтобы не плодить соединения)
_session: aiohttp.ClientSession | None = None

# riot_id_lower -> (ts, rank, region)
_rank_cache: dict[str, tuple[float, str, str]] = {}

# riot_id_lower -> (ts, region)
_region_cache: dict[str, tuple[float, str]] = {}

# Глобальный лимитер HenrikDev (на все endpoints)
_henrik_lock = asyncio.Lock()
_henrik_next_ts: float = 0.0


class ValorantRankError(RuntimeError):
    """Читаемая ошибка для UI (модалка/кнопки)."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def set_http_session(session: aiohttp.ClientSession) -> None:
    global _session
    _session = session


def _payload_status(payload: dict, fallback: int) -> int:
    """Иногда HTTP=200, но внутри JSON status != 200."""
    try:
        s = payload.get("status")
        if isinstance(s, int):
            return s
        if isinstance(s, str) and s.isdigit():
            return int(s)
    except Exception:
        pass
    return fallback


async def _henrik_throttle() -> None:
    """Пейсинг запросов (по умолчанию ~25 req/min)."""
    global _henrik_next_ts
    interval = 60.0 / max(1.0, HENRIKDEV_RPM)

    async with _henrik_lock:
        now = time.time()
        wait = max(0.0, _henrik_next_ts - now)
        _henrik_next_ts = max(_henrik_next_ts, now) + interval

    if wait > 0:
        await asyncio.sleep(wait)


async def _henrik_get_json(url: str, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    """
    GET + JSON + гарантированные ретраи на 429/5xx/сетевые.
    Возвращает: (status, payload)
    """
    if _session is None:
        raise ValorantRankError("HTTP session не установлена (проверь startup порядок).")
    if not HENRIKDEV_API_KEY:
        raise ValorantRankError("Синхронизация ранга не настроена: нет HENRIKDEV_API_KEY.")

    timeout = aiohttp.ClientTimeout(total=12)
    last_exc: Exception | None = None

    for attempt in range(HENRIKDEV_MAX_RETRIES):
        await _henrik_throttle()

        try:
            async with _session.get(url, headers=headers, timeout=timeout) as resp:
                try:
                    payload = await resp.json(content_type=None)
                except Exception:
                    payload = {"status": resp.status, "error": "non-json response"}

                st = _payload_status(payload, resp.status)

                # 429: ждём окно лимита и повторяем
                if st == 429:
                    ra = resp.headers.get("Retry-After")
                    try:
                        wait_s = float(ra) if ra else 60.0
                    except Exception:
                        wait_s = 60.0
                    wait_s = max(wait_s, 5.0)
                    logger.warning(
                        f"HenrikDev 429. Sleep {wait_s:.0f}s and retry "
                        f"(attempt={attempt+1}/{HENRIKDEV_MAX_RETRIES})"
                    )
                    await asyncio.sleep(wait_s)
                    continue

                # 5xx: backoff и повтор
                if st in (500, 502, 503, 504):
                    backoff = min(30.0, 2.0 * (attempt + 1))
                    logger.warning(
                        f"HenrikDev {st}. Sleep {backoff:.0f}s and retry "
                        f"(attempt={attempt+1}/{HENRIKDEV_MAX_RETRIES})"
                    )
                    await asyncio.sleep(backoff)
                    continue

                return st, payload

        except aiohttp.ClientError as e:
            last_exc = e
            backoff = min(20.0, 2.0 * (attempt + 1))
            logger.warning(
                f"HenrikDev network error: {e}. Sleep {backoff:.0f}s and retry "
                f"(attempt={attempt+1}/{HENRIKDEV_MAX_RETRIES})"
            )
            await asyncio.sleep(backoff)

    if last_exc:
        raise ValorantRankError(f"Сетевая ошибка HenrikDev: {last_exc}")
    raise ValorantRankError("Не удалось получить ответ HenrikDev (превышено число попыток).")


def _parse_riot_id(riot_id: str) -> tuple[str, str]:
    raw = (riot_id or "").strip()
    if "#" not in raw:
        raise ValorantRankError("Riot ID должен быть в формате Name#TAG")

    name, tag = raw.split("#", 1)
    name = name.strip()
    tag = tag.strip()

    if not name or not tag:
        raise ValorantRankError("Riot ID должен быть в формате Name#TAG")

    # Мягкие лимиты (у людей бывают пробелы/символы)
    if len(name) > 32 or len(tag) > 16:
        raise ValorantRankError("Слишком длинный Riot ID. Проверь ввод.")

    return name, tag


def _normalize_rank(rank: str | None) -> str:
    r = (rank or "").strip()
    if not r:
        return "Unranked"

    low = r.lower()
    if low in {"unrated", "unranked"}:
        return "Unranked"

    parts = r.replace("_", " ").replace("-", " ").split()
    if len(parts) == 1:
        return parts[0].capitalize()

    if len(parts) >= 2 and parts[1] in {"1", "2", "3"}:
        return f"{parts[0].capitalize()} {parts[1]}"

    return r


async def fetch_valorant_account_region(
    riot_id: str,
    *,
    platform: str | None = None,
) -> str:
    """
    HenrikDev: GET /valorant/v1/account/{name}/{tag}
    Возвращает shard/region (eu/na/ap/kr/latam/br)
    """
    name, tag = _parse_riot_id(riot_id)
    riot_key = f"{name}#{tag}".lower()

    now = time.time()
    cached = _region_cache.get(riot_key)
    if cached and (now - cached[0]) < VALORANT_REGION_CACHE_TTL:
        return cached[1]

    name_q = quote(name, safe="")
    tag_q = quote(tag, safe="")

    plat = (platform or VALORANT_PLATFORM or "pc").lower().strip()
    if plat not in {"pc", "console"}:
        plat = "pc"

    headers = {"Authorization": HENRIKDEV_API_KEY, "Accept": "application/json"}
    url = f"{HENRIKDEV_BASE_URL}/valorant/v1/account/{name_q}/{tag_q}"

    st, payload = await _henrik_get_json(url, headers)

    if st == 404:
        raise ValorantRankError("Игрок не найден. Проверь Riot ID.", status=404)
    if st in (401, 403):
        raise ValorantRankError("Нет доступа к HenrikDev API (проверь ключ/права).", status=st)
    if st != 200:
        raise ValorantRankError(f"Ошибка HenrikDev account: status={st}", status=st)

    data = payload.get("data") or {}
    reg = (data.get("region") or data.get("shard") or "").strip().lower()
    if not reg:
        raise ValorantRankError("Не удалось определить регион аккаунта (пустой ответ).")

    _region_cache[riot_key] = (now, reg)
    return reg


async def fetch_valorant_rank(
    riot_id: str,
    *,
    region: str | None = None,
    platform: str | None = None,
    force: bool = False,
) -> tuple[str, str]:
    """
    Получить актуальный ранг игрока по Riot ID (Name#TAG).
    Возвращает: (rank, region_used)

    HenrikDev: GET /valorant/v3/mmr/{region}/{platform}/{name}/{tag}
    """
    name, tag = _parse_riot_id(riot_id)
    riot_key = f"{name}#{tag}".lower()

    now = time.time()
    if not force:
        cached = _rank_cache.get(riot_key)
        if cached and (now - cached[0]) < VALORANT_RANK_CACHE_TTL:
            return cached[1], cached[2]

    preferred = (region or "").strip().lower()
    if not preferred:
        try:
            preferred = await fetch_valorant_account_region(riot_id, platform=platform)
        except ValorantRankError as e:
            logger.warning(f"account region fallback: {e}")
            preferred = (VALORANT_DEFAULT_REGION or "eu").lower()

    all_regions = ["eu", "na", "ap", "kr", "latam", "br"]
    regions = [preferred] + [r for r in all_regions if r != preferred]

    plat = (platform or VALORANT_PLATFORM or "pc").lower().strip()
    if plat not in {"pc", "console"}:
        plat = "pc"

    name_q = quote(name, safe="")
    tag_q = quote(tag, safe="")

    headers = {"Authorization": HENRIKDEV_API_KEY, "Accept": "application/json"}

    last_404 = False

    for reg in regions:
        url = f"{HENRIKDEV_BASE_URL}/valorant/v3/mmr/{reg}/{plat}/{name_q}/{tag_q}"
        st, payload = await _henrik_get_json(url, headers)

        if st == 404:
            last_404 = True
            continue
        if st in (401, 403):
            raise ValorantRankError("Нет доступа к HenrikDev API (проверь ключ/права).", status=st)
        if st == 503:
            raise ValorantRankError("Сервис рангов временно недоступен (maintenance).", status=st)
        if st != 200:
            logger.warning(f"HenrikDev mmr bad status={st} (region={reg}) payload_keys={list(payload.keys())}")
            continue

        data = payload.get("data") or {}
        current = data.get("current_data") or {}
        rank_raw = current.get("currenttier_patched")

        if not rank_raw:
            highest = data.get("highest_rank") or {}
            rank_raw = highest.get("patched_tier") or highest.get("patchedTier")

        # Если данных нет — не выдаём фальшивый Unranked
        if rank_raw is None or str(rank_raw).strip() == "":
            raise ValorantRankError("Нет данных о ранге (аккаунт Unrated или API не вернул данные).")

        rank = _normalize_rank(str(rank_raw))
        _rank_cache[riot_key] = (now, rank, reg)
        return rank, reg

    if last_404:
        raise ValorantRankError("Игрок не найден. Проверь Riot ID и/или регион аккаунта.", status=404)

    raise ValorantRankError("Не удалось получить ранг. Повтори позже.")
