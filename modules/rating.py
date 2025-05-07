import discord
from discord.ext import commands
from discord import app_commands, Embed
from .database import get_top10


class Rating(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="leaderboard", description="Показать топ-10 игроков по победам")
    async def leaderboard(self, interaction: discord.Interaction):
        top10 = await get_top10()

        if not top10:
            await interaction.response.send_message("❗️ Пока нет данных о победах.", ephemeral=True)
            return

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        description = ""

        for idx, row in enumerate(top10):
            user = interaction.guild.get_member(row["user_id"])
            if user:
                name = f"{user.mention} — {user.display_name}"
            else:
                name = f"ID: {row['user_id']}"
            user = ctx.guild.get_member(row["user_id"])
            mention = user.mention if user else f"ID: {row['user_id']}"
            username = row["username"] if row["username"] else "❓"

            description += f"{medals[idx]} {mention} — **{username}** — 🏆 {row['wins']} побед\n"

        embed = Embed(
            title="🏆 Топ-10 игроков по победам",
            description=description,
            color=discord.Color.gold()
        )
        embed.set_image(url="https://i.pinimg.com/736x/df/c4/ba/dfc4bae602ee1aec9c39bdf01bf888eb.jpg")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Rating(bot))
        embed.set_image(url="https://i.pinimg.com/736x/b2/b6/35/b2b6350611819ed27eaef3b72e7045da.jpg")
        await ctx.send(embed=embed)
