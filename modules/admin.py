import discord
from discord.ext import commands
from discord import app_commands
from modules import database

ALLOWED_ROLES = [1325171549921214494, 1337161337071079556]
@app_commands.guilds(discord.Object(id=1215766036305936394))

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        return any(role.id in ALLOWED_ROLES for role in interaction.user.roles)

    @app_commands.command(name="changerank", description="Изменить ранг и Riot-ник игрока")
    @app_commands.describe(user="Участник", rank="Ранг", username="Riot-ник (опционально)")
    async def changerank(self, interaction: discord.Interaction, user: discord.Member, rank: str, username: str = None):
        username = username or user.display_name
        await database.save_player_profile(user.id, username, rank.capitalize())
        await interaction.response.send_message(
            f"✏️ Обновлён профиль {user.mention}: **{username}**, ранг **{rank.capitalize()}**",
            ephemeral=True
        )

    @app_commands.command(name="changenick", description="Изменить Riot-ник игрока")
    @app_commands.describe(user="Участник", username="Новый Riot-ник")
    async def changenick(self, interaction: discord.Interaction, user: discord.Member, username: str):
        profile = await database.get_player_profile(user.id)
        if profile:
            await database.save_player_profile(user.id, username, profile['rank'])
            await interaction.response.send_message(
                f"🔁 Ник игрока {user.mention} изменён на **{username}**.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ Профиль игрока {user.mention} не найден.",
                ephemeral=True
            )

    @app_commands.command(name="changewins", description="Установить количество побед игрока")
    @app_commands.describe(user="Участник", wins="Новое количество побед")
    async def changewins(self, interaction: discord.Interaction, user: discord.Member, wins: int):
        await database.set_wins(user.id, wins)
        await interaction.response.send_message(
            f"🏆 Победы {user.mention} установлены на **{wins}**.",
            ephemeral=True
        )

    @app_commands.command(name="listplayers", description="Список всех игроков")
    async def listplayers(self, interaction: discord.Interaction):
        profiles = await database.get_all_profiles_with_wins()
        if not profiles:
            await interaction.response.send_message("📭 Нет зарегистрированных игроков.", ephemeral=True)
            return

        description = ""
        for row in profiles:
            user = interaction.guild.get_member(row["user_id"])
            mention = user.mention if user else f"ID: {row['user_id']}"
            description += f"• {mention} — **{row['username']}** ({row['rank']}), 🏆 {row['wins']} побед\n"

        embed = discord.Embed(
            title="📋 Список всех игроков",
            description=description[:4000],
            color=discord.Color.teal()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="adminhelp", description="Показать команды администратора")
    async def adminhelp(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔧 Админ-команды",
            description="Список доступных команд для админов/модераторов:",
            color=discord.Color.red()
        )
        embed.add_field(name="/changerank", value="✏ Изменить ранг игрока", inline=False)
        embed.add_field(name="/changenick", value="🔁 Изменить Riot-ник игрока", inline=False)
        embed.add_field(name="/changewins", value="🏆 Установить количество побед", inline=False)
        embed.add_field(name="/listplayers", value="📋 Показать всех игроков", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Admin(bot))
