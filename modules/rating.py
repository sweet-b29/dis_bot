import discord
from discord.ext import commands
from .database import get_top10
from discord import Embed



def setup(bot):
    @bot.command(name="leaderboard")
    async def leaderboard(ctx):
        top10 = await get_top10()

        if not top10:
            await ctx.send("❗️ Пока нет данных о победах.")
            return

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        description = ""

        for idx, row in enumerate(top10):
            user = ctx.guild.get_member(row["user_id"])
            if user:
                name = f"{user.mention} — {user.display_name}"
            else:
                name = f"ID: {row['user_id']}"

            description += f"{medals[idx]} {idx + 1}. **{name}** — {row['wins']} побед\n"

        embed = Embed(
            title="🏆 Топ-10 игроков по победам",
            description=description,
            color=discord.Color.gold()
        )
        embed.set_image(url="https://i.pinimg.com/736x/b2/b6/35/b2b6350611819ed27eaef3b72e7045da.jpg")
        await ctx.send(embed=embed)
