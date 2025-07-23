import discord
from loguru import logger
from discord import File, Embed
from modules.utils import api_client
from modules.utils.image_generator import generate_draft_image, generate_map_ban_image, generate_final_match_image

MAX_PLAYERS = 4 # Измените при необходимости

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
        self.draft_message = None
        self.available_maps = [
            "Ascent", "Bind", "Haven", "Split", "Icebox",
            "Breeze", "Fracture", "Lotus", "Sunset", "Abyss", "Pearl"
        ]
        self.selected_map = None
        self.banned_maps = []
        self.voice_channels = []
        self.team_sides = {}
        self.lobby = lobby

    async def start(self):
        for captain in self.captains:
            overwrites = self.channel.overwrites
            overwrites[captain] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            await self.channel.edit(overwrites=overwrites)

        await self.channel.send(f"Ход капитана: {self.current_captain.mention}", view=DraftView(self))

        self.draft_message = await self.channel.send(view=DraftView(self))
        logger.info(f"Старт драфта. Первый капитан: {self.current_captain}")

    async def pick_player(self, interaction: discord.Interaction, player):
        self.teams[self.current_captain].append(player)
        if player not in self.available_players:
            await interaction.response.send_message("❗️ Этот игрок уже был выбран.", ephemeral=True)
            return

        self.available_players.remove(player)
        logger.info(f"{self.current_captain.display_name} выбрал игрока {player.display_name}")

        if self.available_players:
            self.switch_captain()
            await self.channel.send(f"Ход капитана: {self.current_captain.mention}", view=DraftView(self))
            await self.draft_message.edit(view=DraftView(self))
            await interaction.response.defer()
        else:
            await self.end_draft()

    async def end_draft(self):
        for captain in self.captains:
            overwrites = self.channel.overwrites
            overwrites[captain] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
            await self.channel.edit(overwrites=overwrites)

        t1 = [await format_player_name(m) for m in [self.captains[0]] + self.teams[self.captains[0]]]
        t2 = [await format_player_name(m) for m in [self.captains[1]] + self.teams[self.captains[1]]]

        await self.draft_message.edit(view=None)
        logger.info("Команды сформированы.")

        players_data = []
        for member in [self.captains[0]] + self.teams[self.captains[0]]:
            profile = await api_client.get_player_profile(member.id)
            if profile:
                players_data.append({"id": profile["id"], "username": profile["username"], "rank": profile["rank"],
                                     "team": "captain_1"})

        for member in [self.captains[1]] + self.teams[self.captains[1]]:
            profile = await api_client.get_player_profile(member.id)
            if profile:
                players_data.append({"id": profile["id"], "username": profile["username"], "rank": profile["rank"],
                                     "team": "captain_2"})

        # Генерируем и отправляем картинку
        image_path = generate_draft_image(players_data, captain_1_id=players_data[0]["id"],
                                          captain_2_id=players_data[len(self.teams[self.captains[0]]) + 1]["id"])
        await self.channel.send(file=discord.File(image_path))
        await self.start_map_draft()

    async def start_map_draft(self):
        self.current_captain = self.captains[1]
        image_path = generate_map_ban_image(
            available_maps=self.available_maps,
            banned_maps=self.banned_maps,
            current_captain=self.current_captain.display_name
        )
        await self.channel.send(file=File(image_path), view=MapDraftView(self))
        logger.info("Начался драфт карт.")

    async def end_map_ban(self):
        logger.info(f"Финальная карта: {self.selected_map}")
        await self.choose_sides()

    async def choose_sides(self):
        self.current_captain = self.captains[0]
        embed = discord.Embed(
            title="🧭 Выбор сторон",
            description=f"{self.current_captain.mention}, выбери сторону для своей команды:",
            color=discord.Color.orange()
        )
        self.side_message = await self.channel.send(embed=embed, view=SideSelectView(self, self.current_captain))

    async def finalize_match(self):
        try:
            # Получаем Django ID капитанов
            captain_1_data = await api_client.get_player_profile(self.captains[0].id)
            captain_2_data = await api_client.get_player_profile(self.captains[1].id)

            logger.debug(f"🔍 Discord ID капитана 1: {self.captains[0].id} ({self.captains[0].display_name})")
            logger.debug(f"🔍 Discord ID капитана 2: {self.captains[1].id} ({self.captains[1].display_name})")

            captain_1_django_id = captain_1_data.get("id")
            captain_2_django_id = captain_2_data.get("id")
            if not captain_1_django_id or not captain_2_django_id:
                logger.error("❌ Не удалось получить Django ID капитанов.")
                return

            # Получаем Django ID всех игроков в командах
            team_1_ids = [captain_1_django_id]
            team_2_ids = [captain_2_django_id]

            for member in self.teams[self.captains[0]]:
                profile = await api_client.get_player_profile(member.id)
                if profile and "id" in profile:
                    team_1_ids.append(profile["id"])
                else:
                    logger.warning(f"❌ Не удалось получить Django ID для участника {member.display_name}")

            for member in self.teams[self.captains[1]]:
                profile = await api_client.get_player_profile(member.id)
                if profile and "id" in profile:
                    team_2_ids.append(profile["id"])
                else:
                    logger.warning(f"❌ Не удалось получить Django ID для участника {member.display_name}")

            map_name = self.selected_map
            sides = {
                "team_1": self.team_sides.get(self.captains[0].id),
                "team_2": self.team_sides.get(self.captains[1].id)
            }

            # Составляем payload
            match_payload = {
                "captain_1": captain_1_django_id,
                "captain_2": captain_2_django_id,
                "team_1": team_1_ids,
                "team_2": team_2_ids,
                "map_name": map_name,
                "sides": sides
            }

            # Отправляем его в API
            match_data = await api_client.create_match(match_payload)
            logger.debug(f"📡 Ответ от API: {match_data}")
            self.match_id = match_data.get("id")
            self.lobby.match_id = self.match_id

            logger.success(f"Матч сохранён в Django: {match_data}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении матча в Django: {e}")

    def switch_captain(self):
        self.current_captain = self.captains[1] if self.current_captain == self.captains[0] else self.captains[0]

    async def send_map_embed(self):
        image_path = generate_final_match_image(
            selected_map=self.selected_map,
            team_sides=self.team_sides,
            captains=self.captains
        )

        if image_path and image_path.exists():
            file = File(image_path, filename="final_match_dynamic.png")
            await self.channel.send(file=file)
        else:
            await self.channel.send("⚠️ Картинка карты не найдена.")

        await self.finalize_match()

    async def create_voice_channels(self):
        category = self.channel.category
        teams = [self.teams[self.captains[0]], self.teams[self.captains[1]]]
        names = [f"♦︎ {self.captains[0].display_name}", f"♣︎ {self.captains[1].display_name}"]

        for idx, (team_members, name) in enumerate(zip(teams, names)):
            overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(connect=False),
                self.guild.me: discord.PermissionOverwrite(connect=True, speak=True),
            }
            for member in team_members + [self.captains[idx]]:
                overwrites[member] = discord.PermissionOverwrite(connect=True, speak=True)

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

        self.draft.available_maps.remove(self.map_name)
        self.draft.banned_maps.append(self.map_name)
        logger.info(f"{interaction.user.display_name} забанил карту: {self.map_name}")

        if len(self.draft.available_maps) == 1:
            self.draft.selected_map = self.draft.available_maps[0]
            await interaction.message.edit(view=None)
            await self.draft.end_map_ban()
        else:
            self.draft.switch_captain()
            image_path = generate_map_ban_image(
                available_maps=self.draft.available_maps,
                banned_maps=self.draft.banned_maps,
                current_captain=self.draft.current_captain.display_name
            )
            file = discord.File(image_path, filename="map_draft_dynamic.png")
            embed = discord.Embed(color=discord.Color.purple())
            embed.set_image(url="attachment://map_draft_dynamic.png")

            await interaction.response.edit_message(embed=embed, view=MapDraftView(self.draft), attachments=[file])

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
