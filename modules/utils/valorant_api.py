from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import quote

import aiohttp
from loguru import logger

# === Конфиг ===

HENRIKDEV_API_KEY = os.getenv("HENRIKDEV_API_KEY") or os.getenv("HENRIK_DEV_API_KEY")
HENRIKDEV_BASE_URL = "https://api.henrikdev.xyz"
VALORANT_DEFAULT_REGION = os.getenv("VALORANT_DEFAULT_REGION", "eu").lower()

# 30 req/min → делаем запас = 1 запрос раз в 2.1 секунды
_MIN_INTERVAL_SECONDS = 2.1

# Кеш рангов, чтобы не дёргать HenrikDev лишний раз
_RANK_CACHE_TTL = int(os.getenv("VALORANT_RANK_CACHE_TTL", "900"))  # 15 минут по умолчанию

# Глобальная сессия для всех запросов к HenrikDev
_session: Optional[aiohttp.ClientSession] = None


def set_http_session(session: aiohttp.ClientSession) -> None:
    """Привязываем уже созданную сессию бота к нашему модулю."""
    global _session
    _session = session


async def get_http_session() -> aiohttp.ClientSession:
    """
    Возвращает текущую сессию.
    Если по какой-то причине её ещё нет — создаёт свою.
    (обычно будет использоваться уже созданная в main.py)
    """
    global _session
    if _session is None:
        _session = aiohttp.ClientSession()
    return _session


async def close_http_session() -> None:
    """Аккуратно закрываем сессию при выключении бота."""
    global _session
    if _session is not None:
        await _session.close()
        _session = None


@dataclass
class ValorantRankError(Exception):
    message: str
    status: int | None = None

    def __str__(self) -> str:
        return self.message

_last_request_ts: float = 0.0
_rank_cache: dict[str, tuple[float, str, str]] = {}  # riot_id_lower -> (ts, rank, region)

async def _respect_rate_limit():
    """
    Очень простой rate-limit:
    не больше 1 запроса к HenrikDev раз в _MIN_INTERVAL_SECONDS.
    """
    global _last_request_ts
    now = time.monotonic()
    delta = now - _last_request_ts
    if delta < _MIN_INTERVAL_SECONDS:
        await asyncio.sleep(_MIN_INTERVAL_SECONDS - delta)
    _last_request_ts = time.monotonic()


def _normalize_rank(raw: Optional[str]) -> str:
    if not raw:
        return "Unranked"
    s = str(raw).strip()
    if s.lower() in {"unrated", "unranked"}:
        return "Unranked"
    return s


def _cache_key(riot_id: str) -> str:
    return riot_id.strip().lower()


def _extract_rank_from_v2(payload: dict) -> Optional[str]:
    """
    Структура v2 mmr (документация HenrikDev):
    {
        "status": 200,
        "data": {
            "current_data": {
                "currenttier_patched": "Gold 2",
                ...
            },
            ...
        }
    }
    """
    data = payload.get("data") or {}
    current = data.get("current_data") or {}
    patched = current.get("currenttier_patched") or current.get("final_rank_patched")
    return patched


async def fetch_valorant_rank(riot_id: str) -> Tuple[str, str]:
    """
    Получить ранг игрока через HenrikDev.

    Возвращает:
        (rank, region)

    Бросает ValorantRankError при любой проблеме
    (404, 429, сетевые ошибки и т.д.).
    """
    if not HENRIKDEV_API_KEY:
        raise ValorantRankError("HENRIKDEV_API_KEY не задан в .env")

    riot_id = (riot_id or "").strip()
    if "#" not in riot_id:
        raise ValorantRankError("Riot ID должен быть в формате Name#TAG")

    name, tag = [part.strip() for part in riot_id.split("#", 1)]
    if not name or not tag:
        raise ValorantRankError("Riot ID должен быть в формате Name#TAG")

    key = _cache_key(riot_id)
    now = time.time()

    # --- кеш ---
    cached = _rank_cache.get(key)
    if cached:
        ts, cached_rank, cached_region = cached
        if now - ts < _RANK_CACHE_TTL:
            return cached_rank, cached_region

    session = await get_http_session()

    region = VALORANT_DEFAULT_REGION
    url = f"{HENRIKDEV_BASE_URL}/valorant/v2/mmr/{region}/{quote(name)}/{quote(tag)}"
    headers = {
        "Authorization": HENRIKDEV_API_KEY,
        "Accept": "application/json",
    }

    await _respect_rate_limit()

    try:
        async with session.get(url, headers=headers) as resp:
            status = resp.status
            try:
                payload = await resp.json()
            except Exception:
                payload = {}

            api_status = payload.get("status")

            # --- разбор статус-кодов ---
            if status == 429 or api_status == 429:
                # Лимит — надо остановить внешний цикл
                raise ValorantRankError("Лимит запросов к HenrikDev (429)", status=429)

            if status == 404 or api_status == 404:
                raise ValorantRankError("Игрок не найден в HenrikDev (404)", status=404)

            if status >= 500 or api_status and api_status >= 500:
                raise ValorantRankError("HenrikDev / Riot временно недоступен", status=status)

            if status != 200 or (api_status not in (None, 200)):
                raise ValorantRankError(f"Неожиданный ответ HenrikDev: HTTP {status}, status={api_status}", status=status)

            # --- парсим ранг ---
            data = payload.get("data") or {}

            # --- ТОЛЬКО текущий ранг (АКТУАЛЬНЫЙ) ---
            data = payload.get("data") or {}

            # v3 current
            current_v3 = data.get("current") or {}
            current_tier_v3 = current_v3.get("tier") or {}
            rank_raw = current_tier_v3.get("name")

            # fallback v2 current (на случай старого ответа API)
            if not rank_raw:
                current_v2 = data.get("current_data") or {}
                rank_raw = current_v2.get("currenttier_patched")

            # ❌ ВАЖНО:
            # ❌ НЕ используем peak
            # ❌ НЕ используем highest_rank
            # ❌ если current пустой → считаем Unranked

            rank = _normalize_rank(rank_raw)

            logger.info(f"[HenrikDev] {riot_id} -> {rank} (region={region})")

            _rank_cache[key] = (now, rank, region)
            return rank, region

    except aiohttp.ClientError as e:
        logger.error(f"[HenrikDev] network error for {riot_id}: {e}")
        raise ValorantRankError("Сетевая ошибка при запросе к HenrikDev") from e
