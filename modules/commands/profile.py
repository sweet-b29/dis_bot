import discord
from discord.ext import commands
from discord import app_commands, Embed
from modules.utils import api_client


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="profile", description="Показать свой профиль")
    async def profile(self, interaction: discord.Interaction):
        profile = await api_client.get_player_profile(interaction.user.id)

        if not profile or "error" in profile:
            await interaction.response.send_message(
                "❌ Профиль не найден. Сначала присоединитесь к лобби.",
                ephemeral=True
            )
            return

        wins = profile.get("wins", 0)
        matches = profile.get("matches", 0)
        username = profile["username"]
        rank = profile["rank"]
        winrate = "—" if matches == 0 else f"{round((wins / matches) * 100, 1)}%"

        embed = Embed(
            title=f"Профиль игрока {interaction.user.display_name}",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Riot-ник", value=username, inline=True)
        embed.add_field(name="Ранг", value=rank, inline=True)
        embed.add_field(name="Победы", value=wins, inline=True)
        embed.add_field(name="Матчей", value=matches, inline=True)
        embed.add_field(name="Победный процент", value=winrate, inline=True)

        view = EditProfileButton()
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class EditProfileButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Редактировать", style=discord.ButtonStyle.primary)
    async def edit_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        from modules.lobby.lobby import PlayerProfileModal
        modal = PlayerProfileModal(None, interaction)
        await interaction.response.send_modal(modal)


async def setup(bot):
    await bot.add_cog(Profile(bot))
