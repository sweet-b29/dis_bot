import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput, Select
import random
from modules import database
from modules.draft import Draft, format_player_name
from loguru import logger
import asyncio

MAX_PLAYERS = 10 # Измените при необходимости



class JoinLobbyButton(View):
    def __init__(self, lobby):
        super().__init__(timeout=None)
        self.lobby = lobby

    @discord.ui.button(label="Присоединиться к лобби", style=discord.ButtonStyle.success)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        profile = await database.get_player_profile(interaction.user.id)

        if profile is None:
            # Показываем модалку, если профиля нет
            modal = PlayerProfileModal(self.lobby, interaction)
            await interaction.response.send_modal(modal)
        else:
            # Профиль уже есть — сразу добавляем в лобби
            await interaction.response.defer()
            await self.lobby.add_member(interaction.user)

        try:
            await interaction.message.edit(
                content=f"👥 Участники: {len(self.lobby.members)}/{MAX_PLAYERS}.",
                view=self
            )
        except discord.NotFound:
            try:
                await interaction.followup.send(
                    content=f"{interaction.user.mention}, вы присоединились к лобби!",
                    ephemeral=True
                )
            except discord.NotFound:
                logger.warning(f"⚠ Interaction от {interaction.user} полностью истёк.")

    @discord.ui.button(label="Выйти из лобби", style=discord.ButtonStyle.danger)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.lobby.members:
            await interaction.response.send_message("❗️ Вы не в лобби.", ephemeral=True)
            return

        self.lobby.members.remove(interaction.user)
        await interaction.response.send_message("🚪 Вы покинули лобби.", ephemeral=True)

        logger.info(f"🚪 Игрок вышел из лобби: {interaction.user.display_name}")

        try:
            await self.lobby.message.edit(
                content=f"👥 Участники: {len(self.lobby.members)}/{MAX_PLAYERS}.",
                view=self
            )
        except discord.NotFound:
            pass


class Lobby:
    count = 0

    def __init__(self, guild: discord.Guild, category_id: int):
        self.message = None
        self.view = None
        Lobby.count += 1
        self.guild = guild
        self.members: list[discord.Member] = []
        self.channel: discord.TextChannel | None = None
        self.category_id = category_id
        self.name = f"◎︎лобби-{Lobby.count}"
        self.captains: list[discord.Member] = []
        self.draft_started = False
        self.victory_registered = False
        self.teams: list[list[discord.Member]] = [[], []]

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

            self.view = JoinLobbyButton(self)
            self.message = await self.channel.send(
                f"🎮 Нажмите на кнопку ниже, чтобы присоединиться к лобби.\n"
                f"👥 Участники: 0/{MAX_PLAYERS}.",
                view=self.view
            )

        except Exception as e:
            logger.error(f"Ошибка при создании канала лобби: {e}")

        logger.info(f"🆕 Создан текстовый канал: {self.channel.name} ({self.channel.id})")

    async def add_member(self, member: discord.Member):
        if member in self.members:
            await self.channel.send(f"{member.mention}, вы уже в лобби.")
            return
        if len(self.members) >= MAX_PLAYERS:
            await self.channel.send(f"{member.mention}, лобби уже заполнено.")
            return

        self.members.append(member)
        await self.channel.send(f"{member.mention} присоединился к лобби ({len(self.members)}/{MAX_PLAYERS})")

        if len(self.members) >= MAX_PLAYERS and not self.draft_started:
            self.draft_started = True
            # Убирает кнопку совсем
            for item in self.view.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await self.message.edit(view=self.view)

            await self.close_lobby()

    async def close_lobby(self):
        self.draft_started = True

        try:
            # Выбор капитанов
            self.captains = random.sample(self.members, 2)

            # Обновление прав в канале
            overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                self.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                self.captains[0]: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                self.captains[1]: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }

            await self.channel.edit(overwrites=overwrites)

            embed = discord.Embed(
                title="✖ Лобби закрыто",
                description="Набрано максимальное количество игроков.",
                color=discord.Color.red()
            )

            captain_1_info = await format_player_name(self.captains[0])
            captain_2_info = await format_player_name(self.captains[1])

            embed.add_field(
                name="⚔ Капитаны выбраны",
                value=f"♦ {captain_1_info}\n♣ {captain_2_info}",
                inline=False
            )
            # Список всех участников лобби
            players_info = []
            for member in self.members:
                info = await format_player_name(member)
                players_info.append(f"- {info}")

            embed.add_field(
                name="🎮 Игроки в лобби",
                value="\n".join(players_info),
                inline=False
            )

            embed.set_footer(text="Переходим к драфту игроков...")

            await self.channel.send(embed=embed)

            await self.start_draft()

            await asyncio.sleep(1200)  # Ждём 20 минут

            await self.channel.send(
                "⚔ Капитаны, подтвердите победу, нажав на кнопку ниже:",
                view=WinButtonView(self)
            )

        except Exception as e:
            logger.error(f"Ошибка при закрытии лобби: {e}")

    async def start_draft(self):
        try:
            draft = Draft(self.guild, self.channel, self.captains, self.members)
            await draft.start()
        except Exception as e:
            logger.error(f"Ошибка при старте драфта: {e}")



    async def register_win(self, interaction: discord.Interaction, team: int):
        if interaction.user not in self.captains:
            await interaction.response.send_message("❌ Только капитан может подтвердить победу!", ephemeral=True)
            return

        if getattr(self, 'victory_registered', False):
            await interaction.response.send_message("❌ Победа уже зафиксирована ранее.", ephemeral=True)
            return

        self.victory_registered = True

        if team == 1:
            winners = await self.get_team_members(1)
        else:
            winners = await self.get_team_members(2)

        for player in winners:
            await database.add_win(player.id)

        await interaction.response.send_message("✅ Победа зафиксирована! Канал удалится через 2 минуты.",
                                                ephemeral=True)
        logger.info(f"✅ Победа команды {team} зафиксирована. Ждём 2 минуты перед удалением канала.")

        # Ждём 2 минуты
        await asyncio.sleep(120)

        try:
            await self.channel.delete(reason="Лобби завершено и победа зафиксирована.")
        except Exception as e:
            logger.error(f"❌ Ошибка при удалении текстового канала: {e}")

    async def get_team_members(self, team_number: int):
        if team_number == 1:
            return [self.captains[0]] + self.teams[0]
        else:
            return [self.captains[1]] + self.teams[1]


class CreateLobbyButton(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Создать новое лобби", style=discord.ButtonStyle.primary, emoji="🎮")
    async def create_lobby_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        category_id = 1321649371837759499  # Указать ID нужной категории
        lobby_instance = Lobby(interaction.guild, category_id)
        await lobby_instance.create_channel()


class PlayerProfileModal(discord.ui.Modal, title="Введите данные профиля"):
    username = discord.ui.TextInput(label="Ваш ник в игре", placeholder="Например: ilyuhaa", max_length=32)
    rank = discord.ui.TextInput(label="Ваш ранг", placeholder="Например: Immortal", max_length=32)

    def __init__(self, lobby, interaction):
        super().__init__()
        self.lobby = lobby
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        valid_ranks = [
            "Iron", "Bronze", "Silver", "Gold",
            "Platinum", "Diamond", "Ascendant", "Immortal", "Radiant"
        ]

        input_rank = str(self.rank).strip().capitalize()

        if input_rank not in valid_ranks:
            await interaction.response.send_message(
                "❌ Неверный ранг. Пожалуйста, введите правильный ранг из списка:\n"
                "Iron, Bronze, Silver, Gold, Platinum, Diamond, Ascendant, Immortal, Radiant",
                ephemeral=True
            )
            return

        await database.save_player_profile(interaction.user.id, str(self.username.value), input_rank)

        await interaction.response.send_message(
            f"✅ Ваш профиль сохранён!\n**Ник:** {self.username.value}\n**Ранг:** {input_rank}",
            ephemeral=True
        )
        await self.lobby.add_member(interaction.user)

class WinButtonView(discord.ui.View):
    def __init__(self, lobby):
        super().__init__(timeout=None)
        self.lobby = lobby

    @discord.ui.button(label="Победа команды ♦", style=discord.ButtonStyle.red)
    async def win_team_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby.register_win(interaction, team=1)

    @discord.ui.button(label="Победа команды ♣", style=discord.ButtonStyle.blurple)
    async def win_team_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.lobby.register_win(interaction, team=2)




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
        view = CreateLobbyButton(bot)
        await ctx.send(embed=embed, view=view)
