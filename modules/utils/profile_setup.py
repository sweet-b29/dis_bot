import discord
from modules.utils import api_client


RANKS: list[str] = [
    "Unranked",
    "Iron 1", "Iron 2", "Iron 3",
    "Bronze 1", "Bronze 2", "Bronze 3",
    "Silver 1", "Silver 2", "Silver 3",
    "Gold 1", "Gold 2", "Gold 3",
    "Platinum 1", "Platinum 2", "Platinum 3",
    "Diamond 1", "Diamond 2", "Diamond 3",
    "Ascendant 1", "Ascendant 2", "Ascendant 3",
    "Immortal 1", "Immortal 2", "Immortal 3",
    "Radiant",
]


def riot_id_is_valid(value: str) -> bool:
    value = (value or "").strip()
    if "#" not in value:
        return False
    name, tag = value.split("#", 1)
    name = name.strip()
    tag = tag.strip()
    return bool(name) and bool(tag)


class RankSelectView(discord.ui.View):
    def __init__(self, user_id: int, *, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.user_id = user_id

        options = [discord.SelectOption(label=r, value=r) for r in RANKS]
        self.select = discord.ui.Select(
            placeholder="Выбери ранг…",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Это меню не для тебя.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        chosen = self.select.values[0]
        try:
            await api_client.update_player_profile(
                interaction.user.id,
                rank=chosen,
                create_if_not_exist=True,
            )
        except Exception:
            await interaction.followup.send("❌ Ошибка при сохранении ранга.", ephemeral=True)
            return

        await interaction.followup.send(f"✅ Ранг сохранён: **{chosen}**.\nТеперь нажми **Обновить** в профиле.", ephemeral=True)
        self.stop()


class RiotIdModal(discord.ui.Modal, title="Профиль игрока"):
    riot_id = discord.ui.TextInput(
        label="Riot ID (Name#TAG)",
        placeholder="Например: Yuriy#KZ1",
        required=True,
        max_length=32,
    )

    def __init__(self, *, user_id: int, default_riot_id: str | None = None):
        super().__init__(timeout=300)
        self.user_id = user_id
        if default_riot_id:
            self.riot_id.default = default_riot_id

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Это окно не для тебя.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        riot_id_value = self.riot_id.value.strip()

        if not riot_id_is_valid(riot_id_value):
            await interaction.followup.send("❌ Укажи Riot ID строго в формате `Name#TAG`.", ephemeral=True)
            return

        try:
            await api_client.update_player_profile(
                interaction.user.id,
                username=riot_id_value,
                create_if_not_exist=True,
            )
        except Exception:
            await interaction.followup.send("❌ Ошибка при сохранении Riot ID.", ephemeral=True)
            return

        await interaction.followup.send(
            "✅ Riot ID сохранён.\nТеперь выбери ранг из списка:",
            view=RankSelectView(interaction.user.id),
            ephemeral=True,
        )