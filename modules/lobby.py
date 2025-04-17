import discord
from discord.ext import commands
from discord.ui import View, Button
import random
from modules.draft import Draft
from loguru import logger

MAX_PLAYERS = 10  # Измените при необходимости


class JoinLobbyButton(View):
    def __init__(self, lobby):
        super().__init__(timeout=None)
        self.lobby = lobby

    @discord.ui.button(label="Присоединиться к лобби", style=discord.ButtonStyle.success)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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


class Lobby:
    count = 0

    def __init__(self, guild: discord.Guild, category_id: int):
        Lobby.count += 1
        self.guild = guild
        self.members: list[discord.Member] = []
        self.channel: discord.TextChannel | None = None
        self.category_id = category_id
        self.name = f"◎︎лобби-{Lobby.count}"
        self.captains: list[discord.Member] = []
        self.draft_started = False

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

            view = JoinLobbyButton(self)
            await self.channel.send(
                f"🎮 Нажмите на кнопку ниже, чтобы присоединиться к лобби.\n"
                f"👥 Участники: 0/{MAX_PLAYERS}.",
                view=view
            )

        except Exception as e:
            logger.error(f"Ошибка при создании канала лобби: {e}")

    async def add_member(self, member: discord.Member):
        if member in self.members:
            await self.channel.send(f"{member.mention}, вы уже в лобби.")
            return

        self.members.append(member)
        await self.channel.send(f"{member.mention} присоединился к лобби ({len(self.members)}/{MAX_PLAYERS})")

        if len(self.members) >= MAX_PLAYERS and not self.draft_started:
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

            embed.add_field(name="⚔ Капитаны выбраны",
                            value=f"♦ {self.captains[0].mention}\n♣ {self.captains[1].mention}", inline=False)
            embed.set_footer(text="Переходим к драфту игроков...")

            await self.channel.send(embed=embed)

            await self.start_draft()

        except Exception as e:
            logger.error(f"Ошибка при закрытии лобби: {e}")

    async def start_draft(self):
        try:
            draft = Draft(self.guild, self.channel, self.captains, self.members)
            await draft.start()
        except Exception as e:
            logger.error(f"Ошибка при старте драфта: {e}")


class CreateLobbyButton(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Создать новое лобби", style=discord.ButtonStyle.primary, emoji="🎮")
    async def create_lobby_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        category_id = 1353766991076393080  # Указать ID нужной категории
        lobby_instance = Lobby(interaction.guild, category_id)
        await lobby_instance.create_channel()


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
