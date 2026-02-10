from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from loguru import logger
from modules.utils import api_client
from modules.utils.valorant_api import fetch_valorant_rank, ValorantRankError


def riot_id_is_valid(riot_id: str) -> bool:
    """
    Мягкая проверка для всех мест, где мы валидируем сохранённый Riot ID.
    Разрешаем любые символы (в том числе пробелы и юникод), главное:
      - есть один символ '#'
      - до и после него есть хоть что-то.
    """
    raw = (riot_id or "").strip()
    if "#" not in raw or raw.count("#") != 1:
        return False
    name, tag = raw.split("#", 1)
    return bool(name.strip()) and bool(tag.strip())

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
    return_updated_only: bool = False,
) -> dict | None:
    """
    Обновляет rank в Django, если:
      - force=True, либо rank_last_sync устарел (TTL).

    Важно:
      - при ошибках API НЕ перезаписывает ранг на Unranked
      - Unranked поверх существующего ранга пишет только если allow_unranked_overwrite=True
    """
    # 1. Берём профиль из Django
    profile = await api_client.get_player(discord_id)
    if not profile:
        return None

    # 2. Riot ID берём из username и валидируем
    username = (profile.get("username") or "").strip()
    if not riot_id_is_valid(username):
        # Нет Riot ID или формат кривой — ничего не трогаем
        return None if return_updated_only else profile

    # 3. Текущий ранг (по умолчанию считаем Unranked)
    current_rank = (profile.get("rank") or "").strip() or "Unranked"

    # 4. TTL — когда в последний раз синкали ранг
    last_sync_raw = (
        profile.get("rank_last_sync")
        or profile.get("rank_last_sync_at")
        or profile.get("rank_last_sync_time")
    )
    last_sync = _parse_iso_dt(last_sync_raw)

    # Если не force и TTL ещё не истёк — выходим
    if not force and not _is_stale(last_sync):
        return None if return_updated_only else profile

    # 5. Тянем актуальный ранг через HenrikDev по username (Riot ID)
    try:
        # force=True сюда приходит только из /syncallranks
        new_rank, region_used = await fetch_valorant_rank(username, force=force)
    except ValorantRankError as e:
        logger.warning(f"[rank_sync] skip update {discord_id} ({username}): {e}")
        return None if return_updated_only else profile

    # 6. Защита от «обнуления»:
    # Был нормальный ранг, а API вернул Unranked — не переписываем,
    # если явно не разрешили allow_unranked_overwrite.
    if new_rank == "Unranked" and current_rank != "Unranked" and not allow_unranked_overwrite:
        logger.warning(
            f"[rank_sync] IGNORE Unranked overwrite for {discord_id} ({username}). "
            f"current={current_rank}, fetched={new_rank}"
        )
        return None if return_updated_only else profile

    # 7. Пишем в Django только после успешного ответа от API
    updated = await api_client.update_player_profile(
        discord_id,
        rank=new_rank,
        create_if_not_exist=False,
        # при желании можно добавить force_rank_update и прокидывать сюда
        # force_rank_update=allow_unranked_overwrite,
    )

    return updated or profile
