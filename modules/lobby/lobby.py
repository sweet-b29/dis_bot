import discord
from discord.ext import commands
from discord.ui import View
import random
from modules.utils import api_client
from modules.lobby.draft import Draft, format_player_name
from loguru import logger
import asyncio
import os

MAX_PLAYERS = 4  # Измените при необходимости


class JoinLobbyButton(View):
    def __init__(self, lobby):
        super().__init__(timeout=None)
        self.lobby = lobby

    @discord.ui.button(label="Присоединиться к лобби", style=discord.ButtonStyle.success)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            profile = await api_client.get_player_profile(interaction.user.id)
        except Exception as e:
            logger.error(f"❌ Ошибка получения профиля: {e}")
            await interaction.response.send_message("⚠ Не удалось получить профиль. Попробуйте позже.", ephemeral=True)
            return

        if not profile or not profile.get("username") or not profile.get("rank"):
            try:
                modal = PlayerProfileModal(self.lobby, interaction)
                await interaction.response.send_modal(modal)
            except Exception as e:
                logger.exception(f"❌ Не удалось отправить модалку регистрации: {e}")
                await interaction.response.send_message("⚠ Не удалось открыть форму регистрации.", ephemeral=True)
            return

        try:
            await interaction.response.defer(ephemeral=True)
        except discord.InteractionResponded:
            pass  # если уже ответили

        if not self.lobby.channel or not self.lobby.guild.get_channel(self.lobby.channel.id):
            logger.warning("❌ Попытка взаимодействия после удаления канала.")
            return

        try:
            await self.lobby.add_member(interaction.user)
        except Exception as e:
            logger.error(f"❌ Не удалось добавить в лобби: {e}")
            await interaction.followup.send("⚠ Не удалось присоединиться к лобби.", ephemeral=True)
            return

        try:
            await interaction.message.edit(
                content=f"👥 Участники: {len(self.lobby.members)}/{MAX_PLAYERS}.",
                view=self
            )
        except discord.NotFound:
            logger.warning("⚠ Сообщение не найдено при попытке обновления (возможно, удалено).")
            try:
                await interaction.followup.send(
                    content=f"{interaction.user.mention}, вы присоединились к лобби!",
                    ephemeral=True
                )
            except (discord.NotFound, discord.HTTPException):
                logger.warning(f"⚠ Interaction истёк или недействителен для {interaction.user}")

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
            logger.warning("⚠ Сообщение лобби не найдено при выходе игрока.")


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
        self.name = f"◎lobby {Lobby.count}"
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
            for item in self.view.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await self.message.edit(view=self.view)

            await self.close_lobby()

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

            player_profiles = []
            for member in self.members:
                profile = await api_client.get_player_profile(member.id)
                rank = profile.get("rank", "Unranked") if profile else "Unranked"
                player_profiles.append((member, rank))

            # Сортируем по убыванию ранга
            sorted_players = sorted(
                player_profiles,
                key=lambda x: RANK_ORDER.get(x[1], 0),
                reverse=True
            )

            self.captains = [sorted_players[0][0], sorted_players[1][0]]
            self.members = [m for m, _ in player_profiles if m not in self.captains]

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
            embed.add_field(name="⚔ Капитаны выбраны", value=f"♦ {captain_1_info}\n♣ {captain_2_info}", inline=False)

            players_info = [f"- {await format_player_name(m)}" for m in self.members]
            embed.add_field(name="🎮 Игроки в лобби", value="\n".join(players_info), inline=False)
            embed.set_footer(text="Переходим к драфту игроков...")

            await self.channel.send(embed=embed)
            await self.start_draft()

            await asyncio.sleep(30) #Переставить потом на 1200
            await self.channel.send("⚔ Капитаны, подтвердите победу, нажав на кнопку ниже:", view=WinButtonView(self))

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

        self.victory_registered = True

        try:
            await api_client.save_match_result(
                match_id=self.match_id,
                winner_team=team
            )
            await interaction.followup.send("✅ Победа зафиксирована! Канал удалится через 10 секунд.", ephemeral=True)
        except Exception as e:
            logger.error(f"❌ Ошибка при сохранении победы: {e}")
            await interaction.followup.send("❌ Ошибка при сохранении победы.", ephemeral=True)
            return

        await asyncio.sleep(10)
        try:
            await self.channel.delete(reason="Лобби завершено и победа зафиксирована.")
        except Exception as e:
            logger.error(f"❌ Ошибка при удалении текстового канала: {e}")


class CreateLobbyButton(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Создать новое лобби", style=discord.ButtonStyle.primary, emoji="🎮")
    async def create_lobby_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        category_id = int(os.getenv("LOBBY_CATEGORY_ID", 0))
        lobby_instance = Lobby(interaction.guild, category_id)
        await lobby_instance.create_channel()


class PlayerProfileModal(discord.ui.Modal, title="Введите данные профиля"):
    username = discord.ui.TextInput(
        label="Ваш ник в игре",
        placeholder="Например: sweet#b29",
        max_length=32
    )
    rank = discord.ui.TextInput(
        label="Ваш актуальный ранг",
        placeholder="Например: Immortal",
        max_length=32
    )

    def __init__(self, lobby, interaction):
        super().__init__(timeout=None)
        self.lobby = lobby
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        username = self.username.value.strip()
        rank = self.rank.value.strip().capitalize()

        valid_ranks = [
            "Iron", "Bronze", "Silver", "Gold",
            "Platinum", "Diamond", "Ascendant", "Immortal", "Radiant",
            "Unranked"
        ]

        if rank not in valid_ranks:
            await interaction.response.send_message(
                "❌ Неверный ранг. Пожалуйста, введите правильный ранг из списка:\n"
                "Iron, Bronze, Silver, Gold, Platinum, Diamond, Ascendant, Immortal, Radiant, Unranked",
                ephemeral=True
            )
            return

        try:
            response = await api_client.update_player_profile(
                interaction.user.id, username, rank, create_if_not_exist=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка при сохранении профиля: {e}", ephemeral=True
            )
            return

        if isinstance(response, dict) and "error" in response:
            await interaction.response.send_message(
                f"❌ {response['error']}", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ Ваш профиль сохранён!\n**Ник:** {username}\n**Ранг:** {rank}",
            ephemeral=True
        )

        if self.lobby:
            try:
                await self.lobby.add_member(interaction.user)
            except Exception as e:
                await interaction.followup.send(
                    f"⚠ Ошибка при добавлении в лобби: {e}", ephemeral=True
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
        view = CreateLobbyButton(bot)
        await ctx.send(embed=embed, view=view)
