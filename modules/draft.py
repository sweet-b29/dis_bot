import discord
from loguru import logger
from discord import File, Embed
from modules import database

MAX_PLAYERS = 10  # Измените при необходимости

async def format_player_name(member: discord.Member) -> str:
    profile = await database.get_player_profile(member.id)
    if profile:
        return f"{member.mention} - {profile['username']} ({profile['rank']})"
    else:
        return f"{member.mention}"


class Draft:
    def __init__(self, guild, channel, captains, players):
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

    async def start(self):
        for captain in self.captains:
            overwrites = self.channel.overwrites
            overwrites[captain] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            await self.channel.edit(overwrites=overwrites)

        embed = discord.Embed(
            title="🏆 Драфт игроков начался!",
            description=f"Первым выбирает капитан {self.current_captain.mention}.",
            color=discord.Color.gold()
        )

        self.draft_message = await self.channel.send(embed=embed, view=DraftView(self))
        logger.info(f"Старт драфта. Первый капитан: {self.current_captain}")

    async def pick_player(self, interaction: discord.Interaction, player):
        self.teams[self.current_captain].append(player)
        self.available_players.remove(player)
        logger.info(f"{self.current_captain.display_name} выбрал игрока {player.display_name}")

        if self.available_players:
            self.switch_captain()
            embed = discord.Embed(
                title="🏆 Драфт продолжается",
                description=f"Теперь выбирает капитан {self.current_captain.mention}",
                color=discord.Color.blurple()
            )
            await self.draft_message.edit(embed=embed, view=DraftView(self))
            await interaction.response.defer()
        else:
            await self.end_draft()

    async def end_draft(self):
        for captain in self.captains:
            overwrites = self.channel.overwrites
            overwrites[captain] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
            await self.channel.edit(overwrites=overwrites)

        embed = discord.Embed(
            title="✅ Драфт завершён",
            description="Команды сформированы. Переходим к выбору карты.",
            color=discord.Color.green()
        )

        t1 = [await format_player_name(m) for m in [self.captains[0]] + self.teams[self.captains[0]]]
        t2 = [await format_player_name(m) for m in [self.captains[1]] + self.teams[self.captains[1]]]

        embed.add_field(name=f"♦ {self.captains[0].display_name}", value="\n".join(t1), inline=True)
        embed.add_field(name=f"♣ {self.captains[1].display_name}", value="\n".join(t2), inline=True)

        await self.draft_message.edit(embed=embed, view=None)
        logger.info("Команды сформированы.")
        await self.start_map_draft()

    async def start_map_draft(self):
        self.current_captain = self.captains[1]
        embed = discord.Embed(
            title="🌍 Драфт карт начался!",
            description=f"Капитан {self.current_captain.mention}, выберите карту для бана.",
            color=discord.Color.purple()
        )

        await self.channel.send(embed=embed, view=MapDraftView(self))
        logger.info("Начался драфт карт.")

    async def choose_sides(self):
        self.current_captain = self.captains[0]
        captain = self.current_captain
        view = SideSelectView(self, captain)

        embed = discord.Embed(
            title="🧭 Выбор сторон",
            description=f"{captain.mention}, выбери сторону для своей команды:",
            color=discord.Color.orange()
        )
        self.side_message = await self.channel.send(embed=embed, view=view)

    async def create_voice_channels(self):
        category = self.channel.category
        teams = [self.teams[self.captains[0]], self.teams[self.captains[1]]]
        names = [f"♦︎ {self.captains[0].display_name}", f"♣︎ {self.captains[1].display_name}"]



        for idx, (team_members, name) in enumerate(zip(teams, names)):
            overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(connect=False),
                self.guild.me: discord.PermissionOverwrite(connect=True, speak=True),

            }

            mod_role = discord.utils.get(self.guild.roles, id=1337161337071079556)
            if mod_role:
                overwrites[mod_role] = discord.PermissionOverwrite(
                    connect=True,
                    speak=True,
                    move_members=True,
                    view_channel=True
                )

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
                        logger.info(f"🔁 Переместил {member.display_name} в голосовой канал {vc.name}")
                    except Exception as e:
                        logger.warning(f"⚠ Не удалось переместить {member.display_name}: {e}")

            self.voice_channels.append(vc)

        await self.channel.send("🎙 Голосовые каналы созданы! Приятной игры.")
        logger.info("Голосовые каналы созданы и игроки распределены.")

        # 🔔 Отправляем напоминания игрокам, которые не в голосовом канале
        for idx, (team_members, captain) in enumerate(
                zip([self.teams[self.captains[0]], self.teams[self.captains[1]]], self.captains)):
            for member in [captain] + team_members:
                if not member.voice:
                    await self.channel.send(
                        f"🔔 {member.mention}, вы ещё не в голосовом канале своей команды! Зайдите как можно скорее.")

    def switch_captain(self):
        self.current_captain = (
            self.captains[1] if self.current_captain == self.captains[0] else self.captains[0]
        )

    async def send_map_embed(self):
        map_name = self.selected_map
        file_path = f"modules/maps/{map_name}.webp"
        team_1 = self.captains[0]
        team_2 = self.captains[1]
        side_1 = self.team_sides[self.captains[0].id]
        side_2 = self.team_sides[self.captains[1].id]

        file = File(file_path, filename="map.webp")
        embed = Embed(
            title="✅ Финальное подтверждение матча!",
            description=(
                f"Игра будет проходить на **{map_name}**.\n"
                f"♦ **{team_1.display_name}** играет за **{side_1}**\n"
                f"♣ **{team_2.display_name}** играет за **{side_2}**"
            ),
            color=discord.Color.green()
        )
        embed.set_image(url="attachment://map.webp")
        await self.channel.send(embed=embed, file=file)

    async def end_map_ban(self):
        logger.info(f"Финальная карта: {self.selected_map}")
        await self.choose_sides()


class DraftView(discord.ui.View):
    def __init__(self, draft):
        super().__init__(timeout=None)
        self.draft = draft

        for player in self.draft.available_players:
            self.add_item(PlayerButton(draft=self.draft, player=player))


class PlayerButton(discord.ui.Button):
    def __init__(self, draft, player):
        # Подгружаем профиль игрока
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
        self.draft = draft

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
            embed = discord.Embed(
                title="🌍 Карта забанена.",
                description=f"Теперь банит капитан {self.draft.current_captain.mention}",
                color=discord.Color.purple()
            )
            await interaction.response.edit_message(embed=embed, view=MapDraftView(self.draft))

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

        side_cases = {
            "Атака": "Атаку",
            "Защита": "Защиту"
        }

        embed = discord.Embed(
            title="✅ Выбор сторон завершён!",
            description=(
            f"**Команда {team_1.display_name}** играет за **{side_cases[chosen_side]}**\n"
            f"**Команда {team_2.display_name}** играет за **{side_cases[other_side]}**"
            ),
            color=discord.Color.green()
        )

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)
        await self.draft.send_map_embed()
        await self.draft.create_voice_channels()


def setup(bot):
    pass  # пока заглушка, можно расширить в будущем
