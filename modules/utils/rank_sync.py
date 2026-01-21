# modules/utils/rank_sync.py
import os
from datetime import datetime, timezone

from loguru import logger
from modules.utils import api_client

# твоя функция, которая реально достаёт ранг по Name#TAG (HenrikDev или другой источник)
from modules.utils.valorant_api import fetch_valorant_rank, ValorantRankError  # см. ниже

RANK_TTL_SECONDS = int(os.getenv("VALORANT_RANK_TTL_SECONDS", "21600"))  # 6 часов по умолчанию

def riot_id_is_valid(value: str | None) -> bool:
    if not value:
        return False
    s = value.strip()
    if "#" not in s:
        return False
    name, tag = s.split("#", 1)
    return bool(name.strip()) and bool(tag.strip())


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _is_stale(last_sync: datetime | None) -> bool:
    if last_sync is None:
        return True
    now = datetime.now(timezone.utc)
    return (now - last_sync).total_seconds() > RANK_TTL_SECONDS


async def ensure_fresh_rank(discord_id: int, *, force: bool = False) -> dict:
    """
    Возвращает профиль игрока.
    Если rank_last_sync отсутствует/просрочен — подтягивает актуальный ранг и обновляет профиль в Django.
    """
    profile = await api_client.get_player_profile(discord_id)
    if not profile or not profile.get("id"):
        return profile or {}

    riot_id = (profile.get("username") or "").strip()
    if not riot_id:
        return profile

    last_sync = _parse_iso_dt(profile.get("rank_last_sync"))
    if not force and not _is_stale(last_sync):
        return profile

    try:
        new_rank, _region_used = await fetch_valorant_rank(riot_id, force=True)
    except ValorantRankError as e:
        logger.warning(f"Rank sync failed for {discord_id} ({riot_id}): {e}")
        return profile
    except Exception as e:
        logger.warning(f"Rank sync unexpected error for {discord_id} ({riot_id}): {e}")
        return profile

    # если ранг уже такой же — всё равно можно обновить timestamp (но это делает Django при rank update).
    if str(profile.get("rank") or "").strip() == str(new_rank or "").strip():
        return profile

    try:
        await api_client.update_player_profile(discord_id=discord_id, username=None, rank=new_rank, create_if_not_exist=False)
    except Exception as e:
        logger.warning(f"Failed to save rank to Django for {discord_id}: {e}")
        return profile

    # возвращаем свежий профиль (с новым rank и rank_last_sync)
    return await api_client.get_player_profile(discord_id)
