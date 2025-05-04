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
            mention = user.mention if user else f"ID: {row['user_id']}"
            username = row["username"] if row["username"] else "❓"

            description += f"{medals[idx]} {mention} — **{username}** — 🏆 {row['wins']} побед\n"

        embed = Embed(
            title="🏆 Топ-10 игроков по победам",
            description=description,
            color=discord.Color.gold()
        )
        embed.set_image(url="https://i.pinimg.com/736x/df/c4/ba/dfc4bae602ee1aec9c39bdf01bf888eb.jpg")
        await ctx.send(embed=embed)
