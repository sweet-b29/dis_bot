import discord
from discord import app_commands
from discord.ext import commands

from modules.utils import api_client


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
    def __init__(self, owner_id: int, riot_id: str):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.riot_id = riot_id

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
            # Не используем внешние API — это должна быть чисто запись в твою Django API/БД
            await interaction.response.edit_message(
                content="❌ Ошибка при сохранении профиля.",
                view=None
            )
            return

        # отключаем меню после выбора
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=f"✅ Профиль сохранён.\nRiot ID: `{self.riot_id}`\nРанг: **{rank}**",
            view=self
        )

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
        label="Riot ID",
        placeholder="Name#TAG",
        required=True,
        max_length=32,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        riot_id_value = self.riot_id.value.strip()
        if not _riot_id_ok(riot_id_value):
            await interaction.followup.send("❌ Укажи Riot ID строго в формате `Name#TAG`.", ephemeral=True)
            return

        view = RankSelectView(owner_id=interaction.user.id, riot_id=riot_id_value)
        await interaction.followup.send("Выбери ранг из списка:", view=view, ephemeral=True)


class ProfileCardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Редактировать", style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditProfileModal())


async def send_profile_card(interaction: discord.Interaction, edit: bool = False):
    discord_id = interaction.user.id

    # читаем только то, что сохранено у тебя в БД (без HenrikDev и без 429)
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

    # ВАЖНО: для кнопки в лобби обычно нужен ephemeral ответ
    if edit:
        # edit имеет смысл только если ты явно редактируешь существующее сообщение
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