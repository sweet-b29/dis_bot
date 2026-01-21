import os
import time
from urllib.parse import quote

import aiohttp
from loguru import logger

HENRIKDEV_BASE_URL = os.getenv("HENRIKDEV_BASE_URL", "https://api.henrikdev.xyz").rstrip("/")
HENRIKDEV_API_KEY = os.getenv("HENRIKDEV_API_KEY", "").strip()

VALORANT_DEFAULT_REGION = os.getenv("VALORANT_DEFAULT_REGION", "eu").strip().lower()
VALORANT_PLATFORM = os.getenv("VALORANT_PLATFORM", "pc").strip().lower()
VALORANT_RANK_CACHE_TTL = float(os.getenv("VALORANT_RANK_CACHE_TTL", "3600"))  # seconds

# Важно: это та же aiohttp-сессия, что и у бота (чтобы не плодить соединения)
_session: aiohttp.ClientSession | None = None

# riot_id_lower -> (ts, rank, region)
_rank_cache: dict[str, tuple[float, str, str]] = {}


class ValorantRankError(RuntimeError):
    """Читаемая ошибка для UI (модалка/кнопки)."""
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def set_http_session(session: aiohttp.ClientSession) -> None:
    global _session
    _session = session


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
    Требует API key. :contentReference[oaicite:3]{index=3}
    """
    if _session is None:
        raise ValorantRankError("HTTP session не установлена (проверь startup порядок).")

    if not HENRIKDEV_API_KEY:
        raise ValorantRankError("Синхронизация ранга не настроена: нет HENRIKDEV_API_KEY.")

    name, tag = _parse_riot_id(riot_id)
    riot_key = f"{name}#{tag}".lower()

    now = time.time()
    if not force:
        cached = _rank_cache.get(riot_key)
        if cached and (now - cached[0]) < VALORANT_RANK_CACHE_TTL:
            return cached[1], cached[2]

    preferred = (region or VALORANT_DEFAULT_REGION or "eu").lower()
    all_regions = ["eu", "na", "ap", "kr", "latam", "br"]
    regions = [preferred] + [r for r in all_regions if r != preferred]

    plat = (platform or VALORANT_PLATFORM or "pc").lower()
    if plat not in {"pc", "console"}:
        plat = "pc"

    # В URL нужны percent-encoded значения (пробелы и т.п.)
    name_q = quote(name, safe="")
    tag_q = quote(tag, safe="")

    headers = {"Authorization": HENRIKDEV_API_KEY, "Accept": "application/json"}

    last_404 = False

    for reg in regions:
        url = f"{HENRIKDEV_BASE_URL}/valorant/v3/mmr/{reg}/{plat}/{name_q}/{tag_q}"
        try:
            async with _session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 404:
                    last_404 = True
                    continue
                if resp.status == 429:
                    raise ValorantRankError("Лимит запросов к ранкам. Повтори позже.", status=429)
                if resp.status in (403, 503):
                    raise ValorantRankError("Сервис рангов временно недоступен (maintenance/ограничение).", status=resp.status)
                if resp.status != 200:
                    raise ValorantRankError(f"Ошибка сервиса рангов: HTTP {resp.status}.", status=resp.status)

                payload = await resp.json(content_type=None)
                rank_raw = payload.get("data", {}).get("current_data", {}).get("currenttier_patched")
                rank = _normalize_rank(rank_raw)

                _rank_cache[riot_key] = (now, rank, reg)
                return rank, reg

        except aiohttp.ClientError as e:
            logger.warning(f"HenrikDev network error (region={reg}): {e}")
            continue

    if last_404:
        raise ValorantRankError("Игрок не найден. Проверь Riot ID и/или регион аккаунта.", status=404)

    raise ValorantRankError("Не удалось получить ранг. Повтори позже.")
