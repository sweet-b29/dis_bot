import discord
from discord import app_commands
from discord.ext import commands

from modules.utils import api_client
from modules.utils.valorant_api import fetch_valorant_rank, ValorantRankError
from modules.commands.profile_setup import riot_id_is_valid
from modules.utils.profiles_cache import profiles_cache


# === Rank options (ВАЖНО: Select <= 25 опций, поэтому делим на 2 меню) ===
LOW_RANKS = [
    "Unranked",
    "Iron 1", "Iron 2", "Iron 3",
    "Bronze 1", "Bronze 2", "Bronze 3",
    "Silver 1", "Silver 2", "Silver 3",
    "Gold 1", "Gold 2", "Gold 3",
]

HIGH_RANKS = [
    "Platinum 1", "Platinum 2", "Platinum 3",
    "Diamond 1", "Diamond 2", "Diamond 3",
    "Ascendant 1", "Ascendant 2", "Ascendant 3",
    "Immortal 1", "Immortal 2", "Immortal 3",
    "Radiant",
]


def _riot_id_ok(value: str) -> bool:
    value = (value or "").strip()
    if "#" not in value:
        return False
    name, tag = value.split("#", 1)
    return bool(name.strip()) and bool(tag.strip())


class RankSelectView(discord.ui.View):
    """
    Сохраняет (username, rank) в БД.
    Если передан after_save — вызовет его после сохранения (например, чтобы автоматически присоединить к лобби).
    """
    def __init__(self, owner_id: int, riot_id: str, after_save=None):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.riot_id = riot_id
        self.after_save = after_save  # async callable(interaction, rank)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    async def _save(self, interaction: discord.Interaction, rank: str):
        try:
            await api_client.update_player_profile(
                self.owner_id,
                username=self.riot_id,
                rank=rank,
                create_if_not_exist=True
            )
        except Exception:
            await interaction.response.edit_message(
                content="❌ Ошибка при сохранении профиля.",
                view=None
            )
            return

        # disable selects
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=f"✅ Профиль сохранён.\nRiot ID: `{self.riot_id}`\nРанг: **{rank}**",
            view=self
        )

        # после сохранения — внешний хук (например автодобавление в лобби)
        if self.after_save:
            try:
                await self.after_save(interaction, rank)
            except Exception:
                # здесь не роняем процесс, просто тихо игнорируем
                pass

    @discord.ui.select(
        placeholder="Выбери ранг (Unranked–Gold)",
        min_values=1,
        max_values=1,
        options=[discord.SelectOption(label=r, value=r) for r in LOW_RANKS],
    )
    async def select_low(self, interaction: discord.Interaction, select: discord.ui.Select):
        await self._save(interaction, select.values[0])

    @discord.ui.select(
        placeholder="Выбери ранг (Platinum–Radiant)",
        min_values=1,
        max_values=1,
        options=[discord.SelectOption(label=r, value=r) for r in HIGH_RANKS],
    )
    async def select_high(self, interaction: discord.Interaction, select: discord.ui.Select):
        await self._save(interaction, select.values[0])


class EditProfileModal(discord.ui.Modal, title="Обновить Riot ID и ранг"):
    riot_id = discord.ui.TextInput(
        label="Riot ID (Name#TAG)",
        placeholder="Например: Yuriy#KZ1",
        max_length=32,
        required=True,
    )

    def __init__(self, *, user_id: int | None = None, default_riot_id: str | None = None):
        super().__init__(timeout=300)
        self.user_id = user_id

        # если в БД уже есть Riot ID — покажем его по умолчанию
        if default_riot_id:
            self.riot_id.default = default_riot_id


    async def on_submit(self, interaction: discord.Interaction):
        # защитимся от использования модалки другим пользователем
        if self.user_id is not None and interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Это окно не для тебя.", ephemeral=True
            )
            return

        # сразу дефёрим, дальше работаем через followup
        await interaction.response.defer(ephemeral=True, thinking=True)

        riot_id_value = self.riot_id.value.strip()

        # базовая проверка формата Riot ID
        if not riot_id_is_valid(riot_id_value):
            await interaction.followup.send(
                "❌ Укажи Riot ID строго в формате `Name#TAG`.",
                ephemeral=True,
            )
            return

        # пробуем получить актуальный ранг из Valorant API
        # по умолчанию считаем Unranked, если что-то пойдёт не так
        rank = "Unranked"
        region_used = "—"

        try:
            rank, region_used = await fetch_valorant_rank(riot_id_value)
        except (ValorantRankError, Exception):
            # Любая ошибка внешнего сервиса не должна ломать регистрацию.
            # Оставляем rank = "Unranked", region_used = "—".
            pass

        # сохраняем профиль в Django API
        try:
            await api_client.update_player_profile(
                discord_id=interaction.user.id,
                username=riot_id_value,
                rank=rank,
                create_if_not_exist=True,
            )
        except Exception:
            await interaction.followup.send(
                "❌ Ошибка при сохранении профиля.",
                ephemeral=True,
            )
            return

        # на всякий случай сбросим кэш профиля
        try:
            await profiles_cache.invalidate(interaction.user.id)
        except Exception:
            # кэш — не критично, молча игнорируем
            pass

        await interaction.followup.send(
            f"✅ Профиль обновлён.\n"
            f"Riot ID: `{riot_id_value}`\n"
            f"Ранг: **{rank}** (region: `{region_used}`)",
            ephemeral=True,
        )


class ProfileCardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Редактировать", style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Подставим сохранённый Riot ID, если он есть
        default_riot = None
        try:
            profile = await api_client.get_player_profile(interaction.user.id)
            default_riot = (profile or {}).get("username")
        except Exception:
            pass

        await interaction.response.send_modal(
            EditProfileModal(owner_id=interaction.user.id, default_riot_id=default_riot)
        )


async def send_profile_card(interaction: discord.Interaction, edit: bool = False):
    discord_id = interaction.user.id

    try:
        profile = await api_client.get_player_profile(discord_id)
    except Exception:
        profile = None

    riot_id = (profile or {}).get("username") or "—"
    rank = (profile or {}).get("rank") or "—"
    wins = (profile or {}).get("wins")
    wins_text = str(wins) if wins is not None else "—"

    embed = discord.Embed(title="Профиль игрока")
    embed.add_field(name="Discord", value=f"<@{discord_id}>", inline=False)
    embed.add_field(name="Riot ID", value=riot_id, inline=True)
    embed.add_field(name="Ранг", value=rank, inline=True)
    embed.add_field(name="Победы", value=wins_text, inline=True)

    view = ProfileCardView()

    if edit:
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.edit_original_response(embed=embed, view=view)
    else:
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profile", description="Показать свой профиль")
    async def profile_cmd(self, interaction: discord.Interaction):
        await send_profile_card(interaction, edit=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
