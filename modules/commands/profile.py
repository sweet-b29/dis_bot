import discord
from discord import app_commands
from discord.ext import commands

from modules.utils import api_client
from modules.utils.valorant_api import fetch_valorant_rank, ValorantRankError


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
    Ручной выбор ранга (fallback), если Valorant API не дал данные.
    Сохраняет (username, rank) в БД.
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

        if self.after_save:
            try:
                await self.after_save(interaction, rank)
            except Exception:
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


class EditProfileModal(discord.ui.Modal, title="Профиль игрока"):
    riot_id = discord.ui.TextInput(
        label="Riot ID (Name#TAG)",
        placeholder="Например: Yuriy#KZ1",
        required=True,
        max_length=32,
    )

    def __init__(self, *, owner_id: int, default_riot_id: str | None = None):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        if default_riot_id:
            self.riot_id.default = default_riot_id

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Это окно не для тебя.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        riot_id_value = self.riot_id.value.strip()
        if not _riot_id_ok(riot_id_value):
            await interaction.followup.send("❌ Укажи Riot ID строго в формате `Name#TAG`.", ephemeral=True)
            return

        # 1) Пробуем автоматически получить ранг
        try:
            rank, region_used = await fetch_valorant_rank(riot_id_value, force=True)
        except ValorantRankError as e:
            # Сохраняем хотя бы Riot ID и даём выбрать ранг вручную
            try:
                await api_client.update_player_profile(
                    interaction.user.id,
                    username=riot_id_value,
                    create_if_not_exist=True
                )
            except Exception:
                await interaction.followup.send("❌ Ошибка при сохранении Riot ID.", ephemeral=True)
                return

            await interaction.followup.send(
                f"⚠ Не удалось получить ранг автоматически: {e}\nВыбери ранг вручную:",
                view=RankSelectView(interaction.user.id, riot_id_value),
                ephemeral=True,
            )
            return

        # 2) Автоуспех — сохраняем username+rank
        try:
            await api_client.update_player_profile(
                interaction.user.id,
                username=riot_id_value,
                rank=rank,
                create_if_not_exist=True
            )
        except Exception:
            await interaction.followup.send("❌ Ошибка при сохранении профиля.", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ Профиль сохранён.\nRiot ID: `{riot_id_value}`\nРанг: **{rank}** (region: `{region_used}`)",
            ephemeral=True
        )

        # Показываем обновлённую карточку профиля отдельным сообщением
        await send_profile_card(interaction, edit=False)


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
