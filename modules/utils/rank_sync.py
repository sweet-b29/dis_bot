from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from loguru import logger

from modules.utils import api_client
from modules.utils.valorant_api import fetch_valorant_rank, ValorantRankError


RANK_TTL = timedelta(seconds=int(os.getenv("RANK_TTL_SECONDS", "21600")))  # 6 часов по умолчанию


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _is_stale(dt: datetime | None) -> bool:
    if dt is None:
        return True
    return (datetime.now(timezone.utc) - dt) > RANK_TTL


async def ensure_fresh_rank(
    discord_id: int,
    *,
    force: bool = False,
    allow_unranked_overwrite: bool = False,
) -> dict | None:
    """
    Обновляет rank в Django, если:
      - force=True, либо rank_last_sync устарел (TTL).
    Критично:
      - при ошибках API НЕ перезаписывает ранг на Unranked
      - Unranked поверх существующего ранга пишет только если allow_unranked_overwrite=True
    """
    profile = await api_client.get_player(discord_id)
    if not profile:
        return None

    username = (profile.get("username") or "").strip()
    if "#" not in username:
        return profile

    current_rank = (profile.get("rank") or "").strip() or "Unranked"

    last_sync_raw = (
        profile.get("rank_last_sync")
        or profile.get("rank_last_sync_at")
        or profile.get("rank_last_sync_time")
    )
    last_sync = _parse_iso_dt(last_sync_raw)

    if not force and not _is_stale(last_sync):
        return profile

    try:
        # force сюда прокидываем только при ручном синке, иначе можно убить лимиты.
        new_rank, region_used = await fetch_valorant_rank(username, force=force)
    except ValorantRankError as e:
        logger.warning(f"[rank_sync] skip update {discord_id} ({username}): {e}")
        return profile

    # Защита от “обнуления”: если был нормальный ранг, а пришёл Unranked — не затираем.
    if new_rank == "Unranked" and current_rank != "Unranked" and not allow_unranked_overwrite:
        logger.warning(
            f"[rank_sync] IGNORE Unranked overwrite for {discord_id} ({username}). "
            f"current={current_rank}, fetched={new_rank}"
        )
        return profile

    # Пишем в Django только после успешного ответа API
    updated = await api_client.update_player_profile(
        discord_id,
        rank=new_rank,
        create_if_not_exist=False,
        # если хочешь — добавь на сервере force_rank_update и прокидывай тут при allow_unranked_overwrite
        # force_rank_update=allow_unranked_overwrite,
    )
    return updated or profile