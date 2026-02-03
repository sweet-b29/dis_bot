import discord
from discord.ext import commands
from discord import app_commands, Embed

from modules.utils import api_client
from modules.utils.image_generator import generate_profile_card

from modules.utils.rank_sync import ensure_fresh_rank

async def send_profile_card(interaction: discord.Interaction, *, edit: bool = False):
    profile = await ensure_fresh_rank(interaction.user.id)
    if not profile or "error" in profile:
        profile = {"username": "—", "rank": "Unranked", "wins": 0, "matches": 0}

    avatar_bytes = None
    try:
        avatar_bytes = await interaction.user.display_avatar.read()
    except Exception:
        pass

    # ВАЖНО: имя функции генерации — то, что у тебя реально используется сейчас
    # Если у тебя называется generate_profile_card — оставь как ниже.
    from modules.utils.image_generator import generate_profile_card

    card_path = generate_profile_card(
        discord_name=interaction.user.display_name,
        riot_username=str(profile.get("username") or "—"),
        rank=str(profile.get("rank") or "Unranked"),
        wins=int(profile.get("wins") or 0),
        matches=int(profile.get("matches") or 0),
        avatar_bytes=avatar_bytes,
    )

    file = discord.File(card_path, filename="profile.png")

    embed = discord.Embed(
        title=f"Профиль: {interaction.user.display_name}",
        color=discord.Color.dark_grey()  # серая лента
    )
    embed.set_image(url="attachment://profile.png")

    view = ProfileView(owner_id=interaction.user.id)

    # безопасно: если interaction уже отвечен — используем followup/edit_original_response
    if edit:
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, attachments=[file], view=view)
        else:
            await interaction.response.edit_message(embed=embed, attachments=[file], view=view)
    else:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, file=file, view=view, ephemeral=True)

def _rank_base(rank: str) -> str:
    r = str(rank or "").strip()
    if not r:
        return "Unranked"
    return r.split()[0].capitalize()


def _rank_color(rank_base: str) -> discord.Color:
    m = {
        "Radiant": discord.Color.gold(),
        "Immortal": discord.Color.red(),
        "Ascendant": discord.Color.green(),
        "Diamond": discord.Color.blue(),
        "Platinum": discord.Color.teal(),
        "Gold": discord.Color.gold(),
        "Silver": discord.Color.light_grey(),
        "Bronze": discord.Color.dark_orange(),
        "Iron": discord.Color.dark_grey(),
        "Unranked": discord.Color.blurple(),
    }
    return m.get(rank_base, discord.Color.blurple())


def _build_embed(member: discord.Member, profile: dict) -> tuple[discord.Embed, discord.File]:
    username = str(profile.get("username") or "—").strip()
    rank_raw = str(profile.get("rank") or "Unranked").strip()
    wins = int(profile.get("wins") or 0)
    matches = int(profile.get("matches") or 0)

    rb = _rank_base(rank_raw)
    color = _rank_color(rb)

    embed = Embed(title=f"Профиль: {member.display_name}", color=color)

    # аватар bytes
    # ВАЖНО: read() работает только в async-контексте — поэтому bytes забираем снаружи.
    # Здесь будет подмена в месте вызова.
    raise RuntimeError("INTERNAL: _build_embed requires avatar_bytes")


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="profile", description="Показать свой профиль")
    async def profile(self, interaction: discord.Interaction):
        await send_profile_card(interaction, edit=False)
        return


class ProfileView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    def _not_owner(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id != self.owner_id

    @discord.ui.button(label="Редактировать", style=discord.ButtonStyle.primary)
    async def edit_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._not_owner(interaction):
            await interaction.response.send_message("❌ Это не ваш профиль.", ephemeral=True)
            return

        from modules.lobby.lobby import PlayerProfileModal
        await interaction.response.send_modal(PlayerProfileModal(interaction))

    @discord.ui.button(label="Обновить", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._not_owner(interaction):
            await interaction.response.send_message("❌ Это не ваш профиль.", ephemeral=True)
            return

        profile = await ensure_fresh_rank(interaction.user.id)
        if not profile or "error" in profile:
            profile = {"username": "—", "rank": "Unranked", "wins": 0, "matches": 0}

        avatar_bytes = None
        try:
            avatar_bytes = await interaction.user.display_avatar.read()
        except Exception:
            pass

        card_path = generate_profile_card(
            discord_name=interaction.user.display_name,
            riot_username=str(profile.get("username") or "—"),
            rank=str(profile.get("rank") or "Unranked"),
            wins=int(profile.get("wins") or 0),
            matches=int(profile.get("matches") or 0),
            avatar_bytes=avatar_bytes,
        )

        file = discord.File(card_path, filename="profile.png")
        rb = _rank_base(str(profile.get("rank") or "Unranked"))
        embed = Embed(title=f"Профиль: {interaction.user.display_name}", color=_rank_color(rb))
        embed.set_image(url="attachment://profile.png")

        # Перерисовываем тот же ephemeral-месседж
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)

    @discord.ui.button(label="Закрыть", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._not_owner(interaction):
            await interaction.response.send_message("❌ Это не ваш профиль.", ephemeral=True)
            return
        await interaction.response.edit_message(view=None)


async def setup(bot):
    await bot.add_cog(Profile(bot))
