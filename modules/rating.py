import discord
from discord.ext import commands
from .database import add_win, get_top10
from loguru import logger

def setup(bot):
    @bot.command(name='rwin')
    async def register_win(ctx):
        winners = ctx.message.mentions
        if not winners:
            await ctx.send("❗ Укажите победителей через упоминания.")
            return

        updated_scores = []
        for member in winners:
            try:
                await add_win(member.id)
                updated_scores.append(f"{member.name}")
            except Exception as e:
                logger.error(f"Ошибка при обновлении победы для {member.name}: {e}")

        if updated_scores:
            await ctx.send("✳︎ Победы засчитаны:\n" + "\n".join(updated_scores))
        else:
            await ctx.send("✖︎ Ошибка при обновлении побед.")

    @bot.command(name='top10')
    async def top_players(ctx):
        try:
            top = await get_top10()
            if not top:
                await ctx.send("ℹ️ Топ-10 игроков пока отсутствует.")
                return

            embed = discord.Embed(title="🏆 Топ-10 игроков сервера", color=0xFFD700)
            for idx, player in enumerate(top, 1):
                embed.add_field(
                    name=f"{idx}. {player['name']}",
                    value=f"{player['wins']} побед",
                    inline=False
                )
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Ошибка при выводе топ-10: {e}")
            await ctx.send("✖︎ Ошибка при получении топ-10.")
