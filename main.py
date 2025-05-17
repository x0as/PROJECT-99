import discord
from discord.ext import commands, tasks
import asyncio

TOKEN = "MTM3Mjc0NTk1NDU2MTYyNjExMg.GbWI4C.bYo8bZlzL3UB0t92G1mtiLx7Oqd_SQG1OsY65M"
STATUS_CHANNEL_ID = 1372938839164981289

HEADMOD_ID = 1368125926600212531
MOD_ID = 1344657921556086875
TRIALMOD_ID = 1359899460506751047
BAN_ROLE_ID = 1361269241487167573

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=commands.when_mentioned_or("!", "."), intents=intents)
status_store = {}
status_board_message = None
warns = {}
bad_words = {"badword1", "badword2", "someoffensiveword"}

async def reply_and_delete(ctx, content):
    try:
        await ctx.message.add_reaction("✅")
        bot_msg = await ctx.send(content)
        await asyncio.sleep(5)
        await bot_msg.delete()
        await ctx.message.delete()
    except:
        pass

async def update_status_board():
    global status_board_message
    channel = bot.get_channel(STATUS_CHANNEL_ID)
    if not channel:
        print("⚠️ Status channel not found.")
        return

    embed = discord.Embed(title="📊 Live Status Board", color=discord.Color.blurple())
    for user_id, status in status_store.items():
        embed.add_field(name=f"<@{user_id}>", value=status, inline=False)

    try:
        if status_board_message:
            await status_board_message.edit(embed=embed)
        else:
            status_board_message = await channel.send(embed=embed)
    except:
        status_board_message = await channel.send(embed=embed)

async def escalate_punishment(ctx, member, reason):
    user_warns = warns.get(member.id, [])
    user_warns.append(reason)
    warns[member.id] = user_warns

    if len(user_warns) == 1:
        await ctx.send(f"⚠️ | {member.mention} has been warned. Reason: {reason}")
    elif len(user_warns) == 2:
        await mute(ctx, member)
        await ctx.send(f"🔇 | {member.mention} has been muted after 2 warnings.")
    elif len(user_warns) >= 3:
        ban_role = discord.utils.get(ctx.guild.roles, id=BAN_ROLE_ID)
        await member.add_roles(ban_role)
        await ctx.send(f"🚫 | {member.mention} received a soft ban (role applied).")

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    await update_status_board()

@bot.event
async def on_message(message):
    await bot.process_commands(message)

@bot.command(name="srn")
async def studying(ctx):
    status_store[ctx.author.id] = "📚 | Studying"
    await reply_and_delete(ctx, f"📚 | {ctx.author.display_name} is now studying.")
    await update_status_board()

bot.run(TOKEN)
