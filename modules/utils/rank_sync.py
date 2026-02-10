from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from modules.utils import api_client
from modules.utils.valorant_api import fetch_valorant_rank, ValorantRankError

# === Riot ID helpers ===

def riot_id_is_valid(riot_id: str) -> bool:
    """
    Более мягкая валидация:
      - ровно один '#'
      - части до и после не пустые
      - допускаем юникод и пробелы (HenrikDev это переварит)
    """
    raw = (riot_id or "").strip()
    if "#" not in raw or raw.count("#") != 1:
        return False
    name, tag = raw.split("#", 1)
    return bool(name.strip()) and bool(tag.strip())


RANK_TTL = timedelta(seconds=int(os.getenv("RANK_TTL_SECONDS", "21600")))  # 6 часов


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _is_stale(last_sync: datetime | None) -> bool:
    if last_sync is None:
        return True
    now = datetime.now(timezone.utc)
    return now - last_sync > RANK_TTL


async def ensure_fresh_rank(
    discord_id: int,
    *,
    force: bool = False,
    allow_unranked_overwrite: bool = False,
    return_updated_only: bool = False,
) -> dict[str, Any] | None:
    """
    Обновляет rank игрока в Django при необходимости.

    Правила:
      * если force=True — всегда идём в HenrikDev, игнорируя TTL;
      * если force=False — идём в HenrikDev только когда rank_last_sync устарел;
      * при ошибках HenrikDev НЕ перезатираем ранг на Unranked;
      * если HenrikDev вернул Unranked, а в БД уже есть рейтинг, то
        перезаписываем его только если allow_unranked_overwrite=True.
    """
    profile = await api_client.get_player(discord_id)
    if not profile:
        logger.warning(f"[rank_sync] player {discord_id} not found in API")
        return None

    username = (profile.get("username") or "").strip()
    if not riot_id_is_valid(username):
        logger.warning(f"[rank_sync] player {discord_id} has invalid Riot ID: {username!r}")
        return None if return_updated_only else profile

    last_sync = _parse_iso_dt(profile.get("rank_last_sync"))
    if not force and not _is_stale(last_sync):
        # данные ещё свежие — ничего не делаем
        return None if return_updated_only else profile

    try:
        new_rank, region_used = await fetch_valorant_rank(username, force=force)
    except ValorantRankError as e:
        logger.warning(f"[rank_sync] skip update {discord_id} ({username}): {e}")
        return None if return_updated_only else profile

    current_rank = (profile.get("rank") or "Unranked").strip() or "Unranked"
    new_rank = (new_rank or "Unranked").strip() or "Unranked"

    if new_rank == current_rank and not allow_unranked_overwrite:
        logger.info(
            f"[rank_sync] {discord_id} ({username}) rank unchanged: {current_rank}"
        )
        return None if return_updated_only else profile

    if (
        new_rank == "Unranked"
        and current_rank != "Unranked"
        and not allow_unranked_overwrite
    ):
        logger.warning(
            f"[rank_sync] IGNORE Unranked overwrite for {discord_id} ({username}). "
            f"current={current_rank}, fetched={new_rank}"
        )
        return None if return_updated_only else profile

    # Пишем в Django только после успешного ответа API
    updated = await api_client.update_player_profile(
        discord_id,
        rank=new_rank,
        create_if_not_exist=False,
    )
    return updated or profile
