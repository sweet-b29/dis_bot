from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from modules.utils import api_client
from modules.utils.valorant_api import fetch_valorant_rank, ValorantRankError

# ===== Валидация Riot ID =====

# Любые символы (в т.ч. кириллица), главное — есть "#"
# и разумные длины name/tag
def riot_id_is_valid(riot_id: str) -> bool:
    riot_id = (riot_id or "").strip()
    if "#" not in riot_id:
        return False
    name, tag = riot_id.split("#", 1)
    name = name.strip()
    tag = tag.strip()
    return 3 <= len(name) <= 16 and 3 <= len(tag) <= 5


# ===== TTL для повторного запроса =====

RANK_TTL = timedelta(
    seconds=int(os.getenv("RANK_TTL_SECONDS", "21600"))
)  # по умолчанию 6 часов


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _is_fresh(last_sync: Optional[datetime]) -> bool:
    if not last_sync:
        return False
    return datetime.now(timezone.utc) - last_sync < RANK_TTL


async def ensure_fresh_rank(
    discord_id: int,
    username: Optional[str] = None,
    *,
    force: bool = False,
    allow_unranked_overwrite: bool = False,
    return_updated_only: bool = False,
    raise_on_fetch_error: bool = False,
):
    """
    Обновить ранг игрока через HenrikDev.

    Параметры:
        discord_id                — Discord ID игрока
        username                  — Riot ID, если уже известен (Name#TAG).
                                    Если None — читаем из Django.
        force                     — игнорировать TTL и всегда ходить в HenrikDev
        allow_unranked_overwrite  — если True, то даже "Unranked" перезаписывает
                                    существующий ранг в БД.
        return_updated_only       — если True, вернуть профиль только если он
                                    действительно обновился; иначе вернуть текущий.

    Возвращает:
        dict профиля игрока (то, что вернула Django API) или None.
    """
    # 1) тянем профиль из Django, чтобы знать текущий ранг и Riot ID
    try:
        profile = await api_client.get_player_profile(discord_id)
    except Exception as e:
        logger.error(f"[rank_sync] failed to load profile {discord_id}: {e}")
        profile = None

    if not profile:
        logger.warning(f"[rank_sync] profile not found for discord_id={discord_id}")
        return None

    current_rank = (profile.get("rank") or "Unranked").strip()
    riot_id = (username or profile.get("username") or "").strip()

    last_sync = _parse_iso_dt(profile.get("rank_last_sync"))

    # 2) TTL — если не force и данные свежие, то просто выходим
    if not force and _is_fresh(last_sync):
        logger.debug(f"[rank_sync] ttl ok for {discord_id}, skip request")
        return None if return_updated_only else profile

    # 3) Без Riot ID обновить ранг нельзя
    if not riot_id or not riot_id_is_valid(riot_id):
        logger.warning(f"[rank_sync] invalid or empty riot_id for {discord_id}: '{riot_id}'")
        return None if return_updated_only else profile

    # 4) Запрашиваем ранг с HenrikDev
    try:
        new_rank, region_used = await fetch_valorant_rank(riot_id)
    except ValorantRankError as e:
        logger.warning(
            f"[rank_sync] HenrikDev error for {discord_id} ({riot_id}): {e} (status={getattr(e, 'status', None)})"
        )
        # В обычных пользовательских сценариях не роняем поток из-за внешнего API.
        # Для админского /syncallranks можно включить явный проброс ошибки.
        if raise_on_fetch_error:
            raise
        return None if return_updated_only else profile

    new_rank = (new_rank or "Unranked").strip()

    # 5) Логика перезаписи
    if new_rank == current_rank:
        # вообще ничего не изменилось
        logger.debug(
            f"[rank_sync] rank unchanged for {discord_id} ({riot_id}): {current_rank}"
        )
        return None if return_updated_only else profile

    if (
        new_rank == "Unranked"
        and current_rank != "Unranked"
        and not allow_unranked_overwrite
    ):
        # Защита, чтобы случайный Unranked не убил нормальный ранг,
        # если мы дергаем неадминские обновления.
        logger.warning(
            f"[rank_sync] IGNORE Unranked overwrite for {discord_id} ({riot_id}). "
            f"current={current_rank}, fetched={new_rank}"
        )
        return None if return_updated_only else profile

    # 6) Пишем в Django только после успешного ответа HenrikDev
    try:
        updated = await api_client.update_player_profile(
            discord_id,
            rank=new_rank,
            create_if_not_exist=False,
        )
    except Exception as e:
        logger.error(f"[rank_sync] failed to update profile {discord_id}: {e}")
        return None if return_updated_only else profile

    logger.info(
        f"[rank_sync] rank updated for {discord_id} ({riot_id}): "
        f"{current_rank} -> {new_rank}"
    )

    return updated or profile
