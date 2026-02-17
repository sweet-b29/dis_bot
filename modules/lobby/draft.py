import asyncio
import discord
from loguru import logger
from discord import File
from modules.utils import api_client
from modules.utils.api_client import get_leaderboard_top
from modules.utils.image_generator import generate_draft_image, generate_map_ban_image, generate_final_match_image
import os

def _parse_role_ids(env_name: str) -> list[int]:
    raw = os.getenv(env_name, "")
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out

# роли, которым разрешён доступ в тим-войсы и перемещение участников
ALLOWED_ROLES: list[int] = _parse_role_ids("ALLOWED_ROLES")


async def format_player_name(member: discord.Member) -> str:
    profile = await api_client.get_player_profile(member.id)
    if isinstance(profile, dict) and profile.get("username") and profile.get("rank"):
        return f"{member.mention} - {profile['username']} ({profile['rank']})"
    return f"{member.mention} - профиль не найден"

class Draft:
    def __init__(self, lobby, guild, channel, captains, players):
        self.guild = guild
        self.channel = channel
        self.captains = captains
        self.available_players = [p for p in players if p not in captains]
        self.teams = {captains[0]: [], captains[1]: []}
        self.current_captain = captains[0]
        self._lock = asyncio.Lock()
        self.draft_message = None
        self.available_maps = [
            "Ascent", "Bind", "Haven", "Split", "Icebox",
            "Breeze", "Fracture", "Lotus", "Sunset", "Abyss", "Pearl", "Corrode"
        ]
        self.selected_map = None
        self.banned_maps = []
        self.voice_channels = []
        self.team_sides = {}
        self.lobby = lobby
        self.map_message: discord.Message | None = None
        self.last_banned_by: discord.Member | None = None
        self._finalize_lock = asyncio.Lock()
        self._match_created = False
        self.match_id = None

    async def _ask_pick_side(self, chooser: discord.Member):
        self.current_captain = chooser
        view = SideSelectView(self, chooser)
        await self.channel.send(
            f"Выбор сторон — ход {chooser.mention}.",
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def start(self):
        # даём писать капитанам
        for captain in self.captains:
            overwrites = self.channel.overwrites
            overwrites[captain] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            await self.channel.edit(overwrites=overwrites)

        self.draft_message = await self.channel.send(
            f"Ход капитана: {self.current_captain.mention}",
            view=DraftView(self)
        )
        logger.info(f"Старт драфта. Первый капитан: {self.current_captain}")

    async def pick_player(self, interaction: discord.Interaction, player):
        async with self._lock:
            if not interaction.response.is_done():
                await interaction.response.defer()

            if player not in self.available_players:
                await interaction.followup.send("❗️ Этот игрок уже был выбран.", ephemeral=True)
                return

            # критичные операции — под локом
            self.available_players.remove(player)
            self.teams[self.current_captain].append(player)
            logger.info(f"{self.current_captain.display_name} выбрал игрока {player.display_name}")

            if self.available_players:
                self.switch_captain()
                if self.draft_message:
                    try:
                        await self.draft_message.edit(
                            content=f"Ход капитана: {self.current_captain.mention}",
                            view=DraftView(self)
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось обновить сообщение драфта: {e}")
            else:
                await self.end_draft()

    async def end_draft(self):
        for captain in self.captains:
            overwrites = self.channel.overwrites
            overwrites[captain] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
            await self.channel.edit(overwrites=overwrites)

        kwargs = {"view": None}
        # если вдруг сообщение было без текста/эмбедов/аттачей — добавим текст,
        # чтобы не получить "Cannot send an empty message".
        if not (self.draft_message.content or self.draft_message.embeds or self.draft_message.attachments):
            kwargs["content"] = "✅ Драфт завершён. Команды сформированы."

        try:
            await self.draft_message.edit(**kwargs)
        except discord.HTTPException as e:
            logger.warning(f"Не удалось отредактировать сообщение драфта: {e}. Пошлём новое.")
            await self.channel.send("✅ Драфт завершён. Команды сформированы.")

        players_data = []
        for member in [self.captains[0]] + self.teams[self.captains[0]]:
            profile = await api_client.get_player_profile(member.id)
            if profile:
                players_data.append({
                    "id": profile["id"],
                    "discord_id": member.id,
                    "username": profile["username"],
                    "display_name": member.display_name,
                    "rank": profile["rank"],
                    "team": "captain_1",
                })

        for member in [self.captains[1]] + self.teams[self.captains[1]]:
            profile = await api_client.get_player_profile(member.id)
            if profile:
                players_data.append({
                    "id": profile["id"],
                    "discord_id": member.id,
                    "username": profile["username"],
                    "display_name": member.display_name,
                    "rank": profile["rank"],
                    "team": "captain_2",
                })

        # Генерируем и отправляем картинку
        capt1 = await api_client.get_player_profile(self.captains[0].id) or {}
        capt2 = await api_client.get_player_profile(self.captains[1].id) or {}

        top_ids = await get_leaderboard_top(3)
        image_path = generate_draft_image(
            players_data,
            captain_1_id=capt1.get("id"),
            captain_2_id=capt2.get("id"),
            top_ids=top_ids,
        )

        file = discord.File(image_path, filename="draft_dynamic.png")
        try:
            if self.draft_message:
                await self.draft_message.edit(
                    content=None, view=None,
                    attachments=[file],
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                await self.channel.send(
                    file=file, content=None,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except Exception as e:
            logger.warning(f"Не удалось обновить сообщение драфта: {e}")
            await self.channel.send(
                file=file, content=None,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        await self.start_map_draft()

    async def start_map_draft(self):
        # первым ходит второй капитан — как у тебя и было
        self.current_captain = self.captains[1]

        image_path = generate_map_ban_image(
            available_maps=self.available_maps,
            banned_maps=self.banned_maps,
            current_captain=self.current_captain.display_name
        )
        file = discord.File(image_path, filename="map_draft_dynamic.png")

        # одно «живое» сообщение: картинка + кнопки
        self.map_message = await self.channel.send(
            file=file,
            content=None,
            view=MapDraftView(self),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        logger.info("Начался драфт карт.")

    async def end_map_ban(self):
        logger.info(f"Финальная карта: {self.selected_map}")

    async def finalize_match(self):
        async with self._finalize_lock:
            if self._match_created or self.match_id:
                logger.warning("finalize_match skipped: match already created")
                return
            self._match_created = True
        """Сохраняем матч в Django. Перед этим валидируем профили всех участников."""
        try:
            async def require_id(member: discord.Member) -> int | None:
                """Возвращает Django ID игрока или None, если профиля нет."""
                profile = await api_client.get_player_profile(member.id)
                if profile and "id" in profile:
                    return profile["id"]
                # дружелюбное сообщение в канал
                await self.channel.send(
                    f"⚠️ {member.mention}, у тебя нет профиля в системе. "
                    f"Открой `/profile` и заполни ник/ранг, затем запусти драфт заново."
                )
                return None

            # Капитаны
            captain_1_id = await require_id(self.captains[0])
            captain_2_id = await require_id(self.captains[1])

            # Команды
            team_1_ids, team_2_ids = [], []
            for m in self.teams[self.captains[0]]:
                pid = await require_id(m)
                if pid:
                    team_1_ids.append(pid)
            for m in self.teams[self.captains[1]]:
                pid = await require_id(m)
                if pid:
                    team_2_ids.append(pid)

            # Если кого-то нет — выходим
            if not captain_1_id or not captain_2_id or \
                    len(team_1_ids) != len(self.teams[self.captains[0]]) or \
                    len(team_2_ids) != len(self.teams[self.captains[1]]):
                self._match_created = False
                await self.channel.send("⏸ Сохранение матча остановлено — не у всех игроков есть профиль.")
                return

            self._match_created = True

            match_payload = {
                "captain_1": captain_1_id,
                "captain_2": captain_2_id,
                "team_1": team_1_ids,
                "team_2": team_2_ids,
                "map_name": self.selected_map,
                "sides": {
                    "team_1": self.team_sides.get(self.captains[0].id),
                    "team_2": self.team_sides.get(self.captains[1].id),
                },
                "mode": getattr(self.lobby, "mode", "5x5"),
                "lobby_name": getattr(self.lobby, "name", None),
                "lobby_id": getattr(self.lobby, "lobby_id", None),
                "external_id": getattr(self.lobby, "external_id", None),
            }

            match_data = await api_client.create_match(match_payload)
            mid = match_data.get("id")
            if not mid:
                self._match_created = False
                await self.channel.send("❌ Матч не создался в Django. Повторите позже.")
                return

            self.match_id = mid
            self.lobby.match_id = mid

            logger.success(f"Матч сохранён в Django: {match_data}")
        except Exception as e:
            self._match_created = False
            logger.error(f"Ошибка при сохранении матча в Django: {e}")
            await self.channel.send("❌ Не удалось сохранить матч. Логи отправлены в консоль.")

    def switch_captain(self):
        self.current_captain = self.captains[1] if self.current_captain == self.captains[0] else self.captains[0]

    async def send_map_embed(self):
        # Определяем, какая команда играет атаку
        cap1_side = self.team_sides.get(self.captains[0].id)
        if cap1_side == "Атака":
            attack_team_members = [self.captains[0]] + self.teams[self.captains[0]]
            defense_team_members = [self.captains[1]] + self.teams[self.captains[1]]
        else:
            attack_team_members = [self.captains[1]] + self.teams[self.captains[1]]
            defense_team_members = [self.captains[0]] + self.teams[self.captains[0]]

        image_path = generate_final_match_image(
            selected_map=self.selected_map,
            attack_players=[m.display_name for m in attack_team_members],
            defense_players=[m.display_name for m in defense_team_members],
        )

        file = File(image_path, filename="final_match_dynamic.png")
        await self.channel.send(
            file=file,
            content=None,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        await self.finalize_match()

    async def create_voice_channels(self):
        category = self.channel.category
        teams = [self.teams[self.captains[0]], self.teams[self.captains[1]]]
        names = [f"♦︎ {self.captains[0].display_name}", f"♣︎ {self.captains[1].display_name}"]

        for idx, (team_members, name) in enumerate(zip(teams, names)):
            overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(connect=False),
                self.guild.me: discord.PermissionOverwrite(connect=True, speak=True, move_members=True),
            }

            # ✅ доступ для ролей (например: модеры, судьи, организаторы)
            for rid in ALLOWED_ROLES:
                role = self.guild.get_role(rid)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(
                        connect=True,
                        speak=True,
                        view_channel=True,
                        move_members=True,
                    )

            # ✅ доступ для игроков матча
            for member in team_members + [self.captains[idx]]:
                overwrites[member] = discord.PermissionOverwrite(connect=True, speak=True, view_channel=True)

            vc = await self.guild.create_voice_channel(
                name=name,
                user_limit=5,
                overwrites=overwrites,
                category=category
            )

            for member in team_members + [self.captains[idx]]:
                if member.voice:
                    try:
                        await member.move_to(vc)
                    except Exception as e:
                        logger.warning(f"⚠ Не удалось переместить {member.display_name}: {e}")

            self.voice_channels.append(vc)
        await self.channel.send("🎙 Голосовые каналы созданы! Приятной игры.")

        # 🔔 Отправляем напоминания игрокам, которые не в голосовом канале
        for idx, (team_members, captain) in enumerate(
                zip([self.teams[self.captains[0]], self.teams[self.captains[1]]], self.captains)):
            for member in [captain] + team_members:
                if not member.voice:
                    await self.channel.send(
                        f"🔔 {member.mention}, вы ещё не в голосовом канале своей команды! Зайдите как можно скорее.")

class DraftView(discord.ui.View):
    def __init__(self, draft):
        super().__init__(timeout=None)
        for player in draft.available_players:
            self.add_item(PlayerButton(draft, player))

class PlayerButton(discord.ui.Button):
    def __init__(self, draft, player):
        super().__init__(label=player.display_name, style=discord.ButtonStyle.secondary)
        self.draft = draft
        self.player = player

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.draft.current_captain:
            await interaction.response.send_message("❌ Сейчас не ваш ход выбирать.", ephemeral=True)
            return

        # мгновенно отключаем кнопку, чтобы предотвратить дабл-клик
        self.disabled = True
        try:
            # если это первое действие по интеракции — редактируем сообщение с этой же вьюхой
            await interaction.response.edit_message(view=self.view)
        except discord.InteractionResponded:
            # если уже ответили, просто обновим сообщение
            await interaction.message.edit(view=self.view)

        await self.draft.pick_player(interaction, self.player)

class MapDraftView(discord.ui.View):
    def __init__(self, draft):
        super().__init__(timeout=None)
        for map_name in draft.available_maps:
            self.add_item(MapButton(draft, map_name))

class MapButton(discord.ui.Button):
    def __init__(self, draft, map_name):
        super().__init__(label=map_name, style=discord.ButtonStyle.secondary)
        self.draft = draft
        self.map_name = map_name

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.draft.current_captain:
            await interaction.response.send_message("❌ Сейчас не ваш ход выбирать карту.", ephemeral=True)
            return

        # подтверждаем интеракцию, чтобы не было ошибок ack
        if not interaction.response.is_done():
            await interaction.response.defer()

        # применяем бан
        if self.map_name not in self.draft.available_maps:
            return
        self.draft.available_maps.remove(self.map_name)
        self.draft.banned_maps.append(self.map_name)
        self.draft.last_banned_by = interaction.user
        logger.info(f"{interaction.user.display_name} забанил карту: {self.map_name}")

        # осталась одна карта → определяем, кто выбирает сторону (ДРУГАЯ команда)
        if len(self.draft.available_maps) == 1:
            self.draft.selected_map = self.draft.available_maps[0]
            # отключаем кнопки
            try:
                for c in self.view.children:
                    c.disabled = True
                if interaction.message:
                    await interaction.message.edit(view=self.view)
            except Exception:
                pass

            chooser = self.draft.captains[0] if self.draft.last_banned_by == self.draft.captains[1] else \
            self.draft.captains[1]
            await self.draft._ask_pick_side(chooser)
            return

        # иначе — обновляем картинку и передаём ход другому
        self.draft.switch_captain()
        img = generate_map_ban_image(
            available_maps=self.draft.available_maps,
            banned_maps=self.draft.banned_maps,
            current_captain=self.draft.current_captain.display_name
        )
        file = discord.File(img, filename="map_draft_dynamic.png")

        # редактируем то же сообщение с картинкой
        if self.draft.map_message:
            await self.draft.map_message.edit(
                attachments=[file],
                content=None,
                view=MapDraftView(self.draft),
                allowed_mentions=discord.AllowedMentions.none(),
            )

class SideSelectView(discord.ui.View):
    def __init__(self, draft: Draft, captain: discord.Member):
        super().__init__(timeout=None)
        self.draft = draft
        self.captain = captain

    @discord.ui.button(label="♦ Атака", style=discord.ButtonStyle.danger)
    async def attack(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.select_side(interaction, "Атака")

    @discord.ui.button(label="♣ Защита", style=discord.ButtonStyle.primary)
    async def defense(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.select_side(interaction, "Защита")

    async def select_side(self, interaction: discord.Interaction, chosen_side: str):
        if interaction.user != self.captain:
            await interaction.response.send_message("❌ Только капитан может выбирать сторону!", ephemeral=True)
            return

        other_side = "Защита" if chosen_side == "Атака" else "Атака"
        team_1 = self.captain
        team_2 = self.draft.captains[1] if self.draft.captains[0] == team_1 else self.draft.captains[0]

        self.draft.team_sides = {
            team_1.id: chosen_side,
            team_2.id: other_side
        }

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(view=self)
        await self.draft.send_map_embed()
        await self.draft.create_voice_channels()

def setup(bot):
    pass
