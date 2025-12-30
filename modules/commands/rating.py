import os
import discord
from discord.ext import commands
from discord import app_commands
from modules.utils import api_client
from modules.utils.image_generator import generate_leaderboard_image

def _parse_allowed_roles(raw: str) -> list[int]:
    out: list[int] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out

ALLOWED_ROLES = _parse_allowed_roles(os.getenv("ALLOWED_ROLES", ""))

def _has_access(member: discord.Member) -> bool:
    perms = getattr(member, "guild_permissions", None)
    if perms and (perms.administrator or perms.manage_guild):
        return True
    if not ALLOWED_ROLES:
        return False
    return any(role.id in ALLOWED_ROLES for role in member.roles)

async def _attach_display_names(guild: discord.Guild | None, data: list[dict]) -> None:
    if not guild:
        return
    for p in data:
        did = p.get("discord_id")
        if not did:
            continue
        try:
            did_int = int(did)
        except Exception:
            continue

        member = guild.get_member(did_int)
        if member is None:
            try:
                member = await guild.fetch_member(did_int)
            except Exception:
                member = None

        if member:
            p["display_name"] = member.display_name

class Rating(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="leaderboard", description="Показать топ-10 игроков по победам")
    async def leaderboard(self, interaction: discord.Interaction):
        if not _has_access(interaction.user):
            await interaction.response.send_message("❌ У вас нет доступа к этой команде.", ephemeral=True)
            return

        await interaction.response.defer()

        data = await api_client.get_top10_players()
        if not isinstance(data, list) or not data:
            await interaction.followup.send("❌ Не удалось загрузить таблицу лидеров.", ephemeral=True)
            return

        await _attach_display_names(interaction.guild, data)

        image_path = generate_leaderboard_image(data)
        file = discord.File(image_path, filename="leaderboard.png")

        view = Top10View()

        await interaction.followup.send(file=file, view=view)

class Top10View(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔄 Обновить", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _has_access(interaction.user):
            await interaction.response.send_message("❌ У вас нет доступа к этой команде.", ephemeral=True)
            return

        await interaction.response.defer()

        data = await api_client.get_top10_players()
        if not isinstance(data, list) or not data:
            await interaction.followup.send("❌ Не удалось обновить список лидеров.", ephemeral=True)
            return

        await _attach_display_names(interaction.guild, data)

        image_path = generate_leaderboard_image(data)
        file = discord.File(image_path, filename="leaderboard.png")

        await interaction.edit_original_response(attachments=[file])

async def setup(bot):
    await bot.add_cog(Rating(bot))
