import discord
from discord.ext import commands
from discord.ui import View
import random
from modules.utils import api_client
from modules.lobby.draft import Draft
from loguru import logger
import asyncio
import time
import os
import re
from modules.utils.image_generator import generate_lobby_image
from modules.utils.api_client import is_banned, get_leaderboard_top
from modules.utils.utils import render_ban_message
from modules.utils.rank_sync import riot_id_is_valid
from modules.utils.valorant_api import fetch_valorant_rank, ValorantRankError
import uuid
from modules.utils.rank_sync import ensure_fresh_rank

LOBBY_COUNTERS = {
    "2x2": 0,
    "3x3": 0,
    "4x4": 0,
    "5x5": 0
}

ROOM_CODE_REGEX = re.compile(r'^[A-Z0-9]{6}$')

PRIZES_TEXT = (
    "Призы:\n"
    " 1️⃣ место <a:arrow:1388296844009930893> 50 $ + роль \n"
    "2️⃣ место <a:arrow:1388296844009930893>** 40 $ + роль** \n"
    "3️⃣ место <a:arrow:1388296844009930893>** 30 $ + роль** \n"
    "4️⃣ место <a:arrow:1388296844009930893> 25 $ \n"
    "5️⃣ место <a:arrow:1388296844009930893> 20 $ \n"
    "6️⃣ место <a:arrow:1388296844009930893> 14 $ \n\n"
    "ДОПОЛНИТЕЛЬНЫЕ КАТЕГОРИИ \n\n"
    "<a:AnimeShooting:1320781753249435760> Лучший хайлайт <a:arrow:1388296844009930893> 12 $ \n"
    "<a:GamerRage:1320781742876921917>  Самый смешной момент <a:arrow:1388296844009930893> 12 $ \n"
    "<a:02yaygifemoji:1331568478808969246> Душа компании <a:arrow:1388296844009930893> 12 $"
)

class ProfilesCache:
    def __init__(self, ttl: float = 60.0):
        self.ttl = ttl
        self._store: dict[int, tuple[float, dict]] = {}
        self._lock = asyncio.Lock()

    async def invalidate(self, discord_id: int) -> None:
        async with self._lock:
            if discord_id in self._store:
                self._store.pop(discord_id, None)

    async def get(self, discord_id: int) -> dict:
        now = time.time()
        async with self._lock:
            ts, data = self._store.get(discord_id, (0, {}))
            if now - ts < self.ttl:
                return data

        # вне локов — сетевой запрос
        data: dict | None = None
        try:
            data = await ensure_fresh_rank(discord_id)
        except Exception as e:
            logger.warning(f"⚠ ensure_fresh_rank failed for {discord_id}: {e}")

        # fallback: если внешний API упал, пробуем взять профиль напрямую из Django
        if not data:
            try:
                data = await api_client.get_player_profile(discord_id)
            except Exception as e:
                logger.warning(f"⚠ get_player_profile fallback failed for {discord_id}: {e}")
                data = {}

        async with self._lock:
            self._store[discord_id] = (now, data or {})
            return data or {}

profiles_cache = ProfilesCache(ttl=60.0)

class JoinLobbyButton(View):
    def __init__(self, lobby):
        super().__init__(timeout=None)
        self.lobby = lobby

    @discord.ui.button(label="Присоединиться к лобби", style=discord.ButtonStyle.success)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Сразу подтверждаем интеракцию, чтобы Discord не вернул "Unknown interaction"
        # если загрузка профиля/ранга займёт больше ~3 секунд.
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            pass

        # Берём профиль из кэша (внутри ensure_fresh_rank → Django + HenrikDev)
        try:
            profile = await profiles_cache.get(interaction.user.id)
        except Exception as e:
            logger.warning(f"⚠ join_button failed while loading profile for {interaction.user.id}: {e}")
            await interaction.followup.send(
                "⚠ Сервис профилей временно недоступен. Попробуйте ещё раз через пару секунд.",
                ephemeral=True,
            )
            return

        # 1) Профиля нет или не заполнен Riot ID → ОДИН раз показываем модалку
        username = (profile or {}).get("username") if profile else ""
        if not (username or "").strip():
            await interaction.followup.send(
                "⚠ У вас не заполнен Riot ID. Используйте /profile, чтобы указать его в формате Name#TAG.",
                ephemeral=True,
            )
            return

        # 2) Кривой формат Riot ID (нет # и т.п.) → даём пользователю поправить
        if not riot_id_is_valid(username):
            await interaction.followup.send(
                "⚠ Riot ID указан в неверном формате. Используйте /profile и введите Name#TAG.",
                ephemeral=True,
            )
            return

        # 3) Пустой ранг — считаем его Unranked, но не мучаем модалкой
        rank = (profile.get("rank") or "").strip() if profile else ""
        if not rank:
            try:
                profile = await api_client.update_player_profile(
                    interaction.user.id,
                    username=username,
                    rank="Unranked",
                    create_if_not_exist=True,
                )
                await profiles_cache.invalidate(interaction.user.id)
            except Exception as e:
                logger.warning(f"Не удалось автоматически выставить Unranked для {interaction.user.id}: {e}")

        # 4) Дальше — твоя текущая логика проверки бана и добавления в лобби
        ban = await is_banned(interaction.user.id)
        if ban.get("banned"):
            text = render_ban_message(
                expires_at_iso=ban.get("expires_at", ""),
                reason=ban.get("reason"),
            )
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
            return

        if not self.lobby.channel or not self.lobby.guild.get_channel(self.lobby.channel.id):
            logger.warning("❌ Попытка взаимодействия после удаления канала.")
            return

        try:
            await self.lobby.add_member(interaction)
        except Exception as e:
            logger.error(f"❌ Не удалось добавить в лобби: {e}")
            await interaction.followup.send("⚠ Не удалось присоединиться к лобби.", ephemeral=True)
            return

        try:
            await interaction.message.edit(view=self)
        except discord.NotFound:
            logger.warning("⚠ Сообщение не найдено при попытке обновления (возможно, удалено).")
            try:
                await interaction.followup.send(
                    content=f"{interaction.user.mention}, вы присоединились к лобби!",
                    ephemeral=True,
                )
            except (discord.NotFound, discord.HTTPException):
                logger.warning(f"⚠ Interaction истёк или недействителен для {interaction.user}")

    @discord.ui.button(label="Выйти из лобби", style=discord.ButtonStyle.danger)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.lobby

        if interaction.user not in lobby.members:
            await interaction.response.send_message("❗️ Вы не в лобби.", ephemeral=True)
            return

        lobby.members.remove(interaction.user)
        await interaction.response.send_message("🚪 Вы покинули лобби.", ephemeral=True)
        logger.info(f"🚪 Игрок вышел из лобби: {interaction.user.display_name}")

        # Собираем профили оставшихся игроков
        async with asyncio.TaskGroup() as tg:
            tasks = {m: tg.create_task(profiles_cache.get(m.id)) for m in lobby.members}
        players_data = []
        for m, t in tasks.items():
            profile = t.result() or {}
            players_data.append({
                "id": profile.get("id"),
                "discord_id": m.id,
                "username": profile.get("username", "—"),
                "display_name": m.display_name,
                "rank": (profile.get("rank") or "Unranked"),
                "wins": profile.get("wins", 0),
                "matches": profile.get("matches", 0),
            })

        # Топ по победам
        top_ids = await get_leaderboard_top(3)  # список discord_id топ-3
        logger.info(f"players_data = {players_data}")
        image_path = generate_lobby_image(players_data, top_ids=top_ids)

        try:
            file = discord.File(image_path, filename="lobby_dynamic.png")
            if lobby.image_message is None:
                lobby.image_message = await lobby.channel.send(
                    file=file,
                    content=None,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                await lobby.image_message.edit(
                    content=None,
                    attachments=[file],
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except Exception as e:
            logger.warning(f"⚠ Не удалось обновить embed: {e}")

    @discord.ui.button(label="Код комнаты", style=discord.ButtonStyle.secondary, emoji="🔑")
    async def code_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        code = (getattr(self.lobby, "room_code", None) or "").strip()
        if not code:
            await interaction.response.send_message("⚠ Код комнаты ещё не указан.", ephemeral=True)
            return
        await interaction.response.send_message(f"🔑 Код комнаты: `{code}`", ephemeral=True)



class Lobby:
    count = 0

    def __init__(self, guild: discord.Guild, category_id: int, max_players: int = 10, mode="2x2"):
        global LOBBY_COUNTERS
        self.message = None
        self.view = None
        self.mode = mode
        Lobby.count += 1
        self.lobby_id = Lobby.count
        LOBBY_COUNTERS[mode] += 1
        self.guild = guild
        self.members: list[discord.Member] = []
        self.channel: discord.TextChannel | None = None
        self.category_id = category_id
        self.name = f"✦{mode}-л{LOBBY_COUNTERS[mode]}"
        self.captains: list[discord.Member] = []
        self.draft_started = False
        self.victory_registered = False
        self.teams: list[list[discord.Member]] = [[], []]
        self.max_players = max_players
        self.image_message: discord.Message | None = None
        self._win_lock = asyncio.Lock()
        self.external_id = str(uuid.uuid4())
        self.room_code: str | None = None
        self.code_message: discord.Message | None = None

    async def _wait_match_id(self, timeout: float = 60.0) -> bool:
        step = 0.2
        waited = 0.0
        while waited < timeout:
            if getattr(self, "match_id", None):
                return True
            await asyncio.sleep(step)
            waited += step
        return False

    async def create_channel(self):
        try:
            category = discord.utils.get(self.guild.categories, id=self.category_id)
            if not category:
                logger.error("❌ Категория не найдена по ID.")
                return

            overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False)
            }

            self.channel = await self.guild.create_text_channel(
                name=self.name,
                overwrites=overwrites,
                category=category
            )

            #Код комнаты (если пустой — показываем “—”)
            code = (self.room_code or "").strip()
            code_display = code if code else "—"

            #1) Topic канала — всегда виден сверху
            try:
                await self.channel.edit(topic=f"🔑 Код комнаты: {code_display} | Режим: {self.mode} | {self.name}")
            except Exception as e:
                logger.warning(f"⚠ Не удалось установить topic канала: {e}")

            #2) Закреплённое сообщение с кодом (видно всем)
            try:
                self.code_message = await self.channel.send(
                    f"🔑 **Код комнаты Valorant:** `{code_display}`\n",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                try:
                    await self.code_message.pin(reason="Код комнаты Valorant")
                except Exception as e:
                    logger.warning(f"⚠ Не удалось закрепить сообщение с кодом: {e}")
            except Exception as e:
                logger.warning(f"⚠ Не удалось отправить сообщение с кодом: {e}")

            #3) Основное сообщение с кнопками + код (на случай если не смотрят topic/pin)
            self.view = JoinLobbyButton(self)
            self.message = await self.channel.send(
                f"🔑 Код комнаты: `{code_display}`\n\n"
                f"Нажмите на кнопку ниже, чтобы присоединиться к лобби.\n",
                view=self.view,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        except Exception as e:
            logger.error(f"Ошибка при создании канала лобби: {e}")

        logger.info(f"🆕 Создан текстовый канал: {self.channel.name} ({self.channel.id})")

    async def add_member(self, interaction: discord.Interaction):
        member = interaction.user

        if len(self.members) >= self.max_players:
            await interaction.followup.send(
                "❌ Лобби уже заполнено, вы не можете присоединиться.",
                ephemeral=True
            )
            return

        if member in self.members:
            try:
                await interaction.response.send_message(
                    "❗ Вы уже в лобби. Повторное нажатие не требуется.",
                    ephemeral=True
                )
            except discord.InteractionResponded:
                await interaction.followup.send(
                    "❗ Вы уже в лобби.",
                    ephemeral=True
                )
            return

        self.members.append(member)

        # Получаем профили всех участников
        players_data = []
        for m in self.members:
            profile = await profiles_cache.get(m.id)
            players_data.append({
                "id": profile.get("id"),
                "discord_id": m.id,
                "username": profile.get("username", "—"),
                "display_name": m.display_name,
                "rank": (profile.get("rank") or "Unranked"),
                "wins": profile.get("wins", 0),
                "matches": profile.get("matches", 0),
            })

        # Генерируем изображение
        top_ids = await get_leaderboard_top(3)  # список discord_id топ-3
        image_path = generate_lobby_image(players_data, top_ids=top_ids)

        file = discord.File(image_path, filename="lobby_dynamic.png")

        if self.image_message is None:
            self.image_message = await self.channel.send(
                file=file,
                content=None,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await self.image_message.edit(
                content=None,
                attachments=[file],
                allowed_mentions=discord.AllowedMentions.none(),
            )

        if len(self.members) >= self.max_players and not self.draft_started:
            self.draft_started = True
            for item in self.view.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await self.message.edit(view=self.view)
            await self.close_lobby()

        for m in list(self.members):
            ban = await is_banned(m.id)
            if ban.get("banned"):
                self.members.remove(m)
                await self.channel.send(
                    f"⛔ {m.mention} был исключён из лобби (забанен до {ban.get('expires_at')})."
                )

    async def close_lobby(self):
        self.draft_started = True

        if len(self.members) < 2:
            await self.channel.send("❌ Недостаточно игроков для драфта. Лобби будет закрыто.")
            await self.channel.delete(reason="Недостаточно игроков для драфта.")
            return

        try:
            RANK_ORDER = {
                "Radiant": 10, "Immortal": 9, "Ascendant": 8, "Diamond": 7,
                "Platinum": 6, "Gold": 5, "Silver": 4, "Bronze": 3,
                "Iron": 2, "Unranked": 1
            }

            def rank_base(rank: str) -> str:
                # "Immortal 2" -> "Immortal"
                return str(rank or "Unranked").strip().split()[0].title()

            async with asyncio.TaskGroup() as tg:
                tasks = {m: tg.create_task(profiles_cache.get(m.id)) for m in self.members}

            player_profiles = []
            for member, task in tasks.items():
                profile = task.result() or {}
                base = rank_base(profile.get("rank", "Unranked"))
                score = RANK_ORDER.get(base, 1)
                player_profiles.append((member, score))

            # сортируем по силе
            sorted_players = sorted(player_profiles, key=lambda x: x[1], reverse=True)

            # пул капитанов = топ-4 (или меньше, если игроков меньше)
            pool_size = min(4, len(sorted_players))
            captain_pool = [m for m, _ in sorted_players[:pool_size]]

            # выбираем 2 капитана рандомно из пула
            self.captains = random.sample(captain_pool, 2)

            # кто выбирает первым — тоже рандом
            random.shuffle(self.captains)

            # остальные участники
            self.members = [m for m, _ in player_profiles if m not in self.captains]

            overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                self.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                self.captains[0]: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                self.captains[1]: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            await self.channel.edit(overwrites=overwrites)

            # 🔁 Генерация картинки финального состава
            players_data = []
            for m in self.members:
                profile = await profiles_cache.get(m.id)
                players_data.append({
                    "id": profile.get("id"),
                    "discord_id": m.id,
                    "username": profile.get("username", "—"),
                    "display_name": m.display_name,
                    "rank": (profile.get("rank") or "Unranked"),
                    "wins": profile.get("wins", 0),
                    "matches": profile.get("matches", 0),
                })

            top_ids = await get_leaderboard_top(3)  # список discord_id топ-3
            image_path = generate_lobby_image(players_data, top_ids=top_ids)

            file = discord.File(image_path, filename="lobby_dynamic.png")
            if self.image_message is None:
                self.image_message = await self.channel.send(
                    file=file,
                    content=None,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                await self.image_message.edit(
                    content=None,
                    attachments=[file],
                    allowed_mentions=discord.AllowedMentions.none(),
                )

            await self.start_draft()

            await asyncio.sleep(1200)

            # ✅ если матч не создался — не показываем кнопки победы
            if not await self._wait_match_id(timeout=60.0):
                await self.channel.send(
                    "⚠ Матч не создан (нет match_id). Победу сейчас зафиксировать нельзя. "
                    "Проверьте, что у всех есть профиль и API доступен."
                )
                return

            await self.channel.send(
                "⚔ Капитаны, подтвердите победу, нажав на кнопку ниже:",
                view=WinButtonView(self)
            )

        except Exception as e:
            logger.error(f"Ошибка при закрытии лобби: {e}")

    async def start_draft(self):
        try:
            self.draft = Draft(self, self.guild, self.channel, self.captains, self.members)
            await self.draft.start()
        except Exception as e:
            logger.error(f"Ошибка при старте драфта: {e}")

    async def register_win(self, interaction: discord.Interaction, team: int):
        await interaction.response.defer(ephemeral=True)

        if interaction.user not in self.captains:
            await interaction.followup.send("❌ Только капитан может подтвердить победу!", ephemeral=True)
            return

        if self.victory_registered:
            await interaction.followup.send("❌ Победа уже зафиксирована ранее.", ephemeral=True)
            return

        if not hasattr(self, "match_id") or self.match_id is None:
            await interaction.followup.send("❌ ID матча не найден. Невозможно сохранить результат.", ephemeral=True)
            return

        async with self._win_lock:
            if self.victory_registered:
                await interaction.followup.send("❌ Победа уже зафиксирована ранее.", ephemeral=True)
                return

            ok, data = await api_client.save_match_result(self.match_id, team)
            if not ok:
                await interaction.followup.send("❌ Не удалось сохранить победу. Попробуйте ещё раз.", ephemeral=True)
                return

            self.victory_registered = True
            await interaction.followup.send("✅ Победа зафиксирована! Канал удалится через 10 секунд.", ephemeral=True)

        await asyncio.sleep(10)
        try:
            await self.channel.delete(reason="Лобби завершено и победа зафиксирована.")
        except Exception as e:
            logger.error(f"❌ Ошибка при удалении текстового канала: {e}")


class LobbyRoomCodeModal(discord.ui.Modal, title="Введите код комнаты Valorant"):
    room_code = discord.ui.TextInput(
        label="Код комнаты",
        placeholder="Введите код комнаты кастомки",
        max_length=6,
        required=True,
    )

    def __init__(self, *, size: int, mode: str, bot: commands.Bot):
        super().__init__(timeout=300)
        self.size = size
        self.mode = mode
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        code = self.room_code.value.strip()

        if not ROOM_CODE_REGEX.fullmatch(code):
            await interaction.followup.send(
                "❌ Неверный формат кода комнаты.",
                ephemeral=True,
            )
            return

        category_id = int(os.getenv("LOBBY_CATEGORY_ID", 0))
        lobby_instance = Lobby(interaction.guild, category_id, max_players=self.size * 2, mode=self.mode)
        lobby_instance.room_code = code

        await lobby_instance.create_channel()

        await interaction.followup.send(
            f"Лобби создано: {lobby_instance.channel.mention}\n🔑 Код комнаты: `{code}`",
            ephemeral=True
        )


class LobbyMenuView(View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

        self.add_item(LobbySizeButton(label="2x2", size=2, bot=bot))
        self.add_item(LobbySizeButton(label="3x3", size=3, bot=bot))
        self.add_item(LobbySizeButton(label="4x4", size=4, bot=bot))
        self.add_item(LobbySizeButton(label="5x5", size=5, bot=bot))
        self.add_item(ProfileButton())
        self.add_item(PrizesButton())

class LobbySizeButton(discord.ui.Button):
    def __init__(self, label, size, bot):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.size = size
        self.mode = label
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        modal = LobbyRoomCodeModal(size=self.size, mode=self.mode, bot=self.bot)
        await interaction.response.send_modal(modal)

class ProfileButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Профиль", style=discord.ButtonStyle.secondary, emoji="👤")

    async def callback(self, interaction: discord.Interaction):
        from modules.commands.profile import send_profile_card
        await send_profile_card(interaction, edit=False)

class PrizesButton(discord.ui.Button):
    def __init__(self):
        # primary = самый заметный (blurple). "Жёлтого" нет.
        super().__init__(label="Призы", style=discord.ButtonStyle.primary, emoji="🏆")

    async def callback(self, interaction: discord.Interaction):
        # показываем ТОЛЬКО нажавшему
        if not interaction.response.is_done():
            await interaction.response.send_message(PRIZES_TEXT, ephemeral=True)
        else:
            await interaction.followup.send(PRIZES_TEXT, ephemeral=True)


class PlayerProfileModal(discord.ui.Modal, title="Введите Riot ID (Name#TAG)"):
    username = discord.ui.TextInput(
        label="Riot ID",
        placeholder="Например: sweet#b29",
        max_length=32,
        required=True,
    )

    def __init__(self, interaction: discord.Interaction, *, lobby: "Lobby|None" = None):
        super().__init__(timeout=None)
        self.lobby = lobby
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        # 1) Сразу подтверждаем interaction (иначе 404 Unknown interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)

        riot_id = self.username.value.strip()

        # 2) Проверка формата Riot ID
        if "#" not in riot_id or riot_id.count("#") != 1:
            await interaction.followup.send(
                "❌ Riot ID должен быть в формате `Name#TAG` (пример: `sweet#b29`).",
                ephemeral=True
            )
            return

        name, tag = riot_id.split("#", 1)
        if not name or not tag:
            await interaction.followup.send(
                "❌ Riot ID должен быть в формате `Name#TAG` (пример: `sweet#b29`).",
                ephemeral=True
            )
            return

        # 3) Тянем актуальный ранг
        # по умолчанию считаем Unranked — регистрация не должна падать из-за внешнего сервиса
        rank = "Unranked"
        region_used = "—"

        try:
            rank, region_used = await fetch_valorant_rank(riot_id)
        except (ValorantRankError, Exception):
            # Любые проблемы HenrikDev игнорируем, оставляем Unranked
            pass

        # 4) Сохраняем профиль
        try:
            await api_client.update_player_profile(
                interaction.user.id,
                username=riot_id,
                rank=rank,
                create_if_not_exist=True
            )
        except Exception:
            await interaction.followup.send("❌ Ошибка при сохранении профиля.", ephemeral=True)
            return

        # сброс кэша, чтобы сразу рисовалась новая инфа
        await profiles_cache.invalidate(interaction.user.id)

        # 5) Если модалка открывалась при входе в лобби — сразу добавляем
        if self.lobby:
            try:
                await self.lobby.add_member(interaction)
                await interaction.followup.send(
                    f"✅ Профиль сохранён и вы добавлены в лобби.\n"
                    f"Ник: `{riot_id}`\nРанг: **{rank}** (region: `{region_used}`)",
                    ephemeral=True
                )
                return
            except Exception:
                await interaction.followup.send(
                    f"⚠ Профиль сохранён, но вход в лобби не удался.\n"
                    f"Ник: `{riot_id}`\nРанг: **{rank}** (region: `{region_used}`)",
                    ephemeral=True
                )
                return

        await interaction.followup.send(
            f"✅ Профиль сохранён.\nНик: `{riot_id}`\nРанг: **{rank}** (region: `{region_used}`)",
            ephemeral=True
        )


class WinButtonView(discord.ui.View):
    def __init__(self, lobby):
        super().__init__(timeout=None)
        self.lobby = lobby

        captain_1 = lobby.captains[0].display_name
        captain_2 = lobby.captains[1].display_name

        self.add_item(WinButton(label=f"Победа команды {captain_1}", style=discord.ButtonStyle.red, team=1, lobby=lobby))
        self.add_item(WinButton(label=f"Победа команды {captain_2}", style=discord.ButtonStyle.blurple, team=2, lobby=lobby))


class WinButton(discord.ui.Button):
    def __init__(self, label: str, style: discord.ButtonStyle, team: int, lobby):
        super().__init__(label=label, style=style)
        self.team = team
        self.lobby = lobby

    async def callback(self, interaction: discord.Interaction):
        await self.lobby.register_win(interaction, team=self.team)



def setup(bot: commands.Bot):
    @bot.command(name="send_lobby_button")
    async def send_lobby_button(ctx: commands.Context):
        embed = discord.Embed(
            title="🎮 Создание лобби",
            description=(
                "Нажмите кнопку **Создать новое лобби**, чтобы начать сбор игроков.\n\n"
                "🔹 **Максимальное количество игроков:** `10`\n"
                "🔹 После сбора игроков автоматически выберутся капитаны и начнётся драфт команд.\n"
                "🔹 После драфта будут автоматически созданы приватные голосовые каналы для команд."
            ),
            color=discord.Color.blurple()
        )

        embed.set_footer(text="Удачи и приятной игры!")
        view = LobbyMenuView(bot)
        await ctx.send(embed=embed, view=view)
