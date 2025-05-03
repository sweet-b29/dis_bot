import discord
from discord.ext import commands
from modules import database

ALLOWED_ROLES = [1325171549921214494, 1337161337071079556]

def has_any_role():
    async def predicate(ctx):
        return any(role.id in ALLOWED_ROLES for role in ctx.author.roles)
    return commands.check(predicate)

def setup(bot):
    @bot.command(name="changerank")
    @has_any_role()
    async def set_rank(ctx, member: discord.Member, rank: str, *, username: str = None):
        if username is None:
            username = member.display_name
        await database.save_player_profile(member.id, username, rank.capitalize())
        await ctx.send(f"✏️ Обновлён профиль {member.mention}: **{username}**, ранг **{rank.capitalize()}**")

    @bot.command(name="changenick")
    @has_any_role()
    async def set_nick(ctx, member: discord.Member, *, username: str):
        profile = await database.get_player_profile(member.id)
        if profile:
            await database.save_player_profile(member.id, username, profile['rank'])
            await ctx.send(f"🔁 Ник игрока {member.mention} изменён на **{username}**.")
        else:
            await ctx.send(f"❌ Профиль игрока {member.mention} не найден.")

    @bot.command(name="listplayers")
    @has_any_role()
    async def list_players(ctx):
        profiles = await database.get_all_profiles_with_wins()
        if not profiles:
            await ctx.send("📭 Нет зарегистрированных игроков.")
            return

        description = ""
        for row in profiles:
            user = ctx.guild.get_member(row["user_id"])
            mention = user.mention if user else f"ID: {row['user_id']}"
            description += f"• {mention} — **{row['username']}** ({row['rank']}), 🏆 {row['wins']} побед\n"

        embed = discord.Embed(
            title="📋 Список всех игроков",
            description=description[:4000],  # Discord ограничение на 6000, лучше оставить запас
            color=discord.Color.teal()
        )
        await ctx.send(embed=embed)

    @bot.command(name="changewins")
    @has_any_role()
    async def set_wins(ctx, member: discord.Member, wins: int):
        await database.set_wins(member.id, wins)
        await ctx.send(f"🔁 Победы {member.mention} установлены на **{wins}**.")

    @bot.command(name="adminhelp")
    @has_any_role()  # Только для нужных ролей
    async def admin_help(ctx):
        embed = discord.Embed(
            title="🔧 Админ-команды",
            description="Список доступных команд для админов/модераторов:",
            color=discord.Color.red()
        )

        embed.add_field(name=".changerank @user Immortal", value="✏ Изменить ранг игрока", inline=False)
        embed.add_field(name=".changenick @user RiotNick", value="🔁 Изменить Riot-ник игрока", inline=False)
        embed.add_field(name=".changewins @user 5", value="🏆 Установить количество побед", inline=False)
        embed.add_field(name=".listplayers", value="📋 Показать всех игроков с их рангами и победами", inline=False)

        await ctx.send(embed=embed)

