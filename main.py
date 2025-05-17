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
status_emojis = {
    "srn": "✅ STUDYING",
    "f": "🟡 FREE",
    "dl": "🟣 OTHER WORK",
    "s": "🔴 SLEEPING",
    "b": "🔵 ON BREAK"
}

status_messages = {
    "srn": "📚 | **{user}** is studying. Let them focus. ✨",
    "b": "☕ | **{user}** is on a short break. ☕",
    "dl": "🛠️ | **{user}** is busy with something else. 🕒",
    "s": "😴 | **{user}** is sleeping. 🌙"
}

def has_role(member, role_id):
    return any(role.id == role_id for role in member.roles)

def mod_level(member):
    if has_role(member, HEADMOD_ID):
        return "headmod"
    elif has_role(member, MOD_ID):
        return "mod"
    elif has_role(member, TRIALMOD_ID):
        return "trialmod"
    return None

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

    category_map = {key: [] for key in status_emojis}
    for user_id, status in status_store.items():
        if status in category_map:
            category_map[status].append(f"<@{user_id}>")

    embed = discord.Embed(title="📊 Live Status Board", description="Current activity of all users", color=discord.Color.blurple())
    for key, emoji in status_emojis.items():
        users = category_map[key]
        display = "\n".join(users) if users else "*No users*"
        embed.add_field(name=f"{emoji} — {len(users)}", value=display, inline=False)

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
    if message.author.bot:
        return

    if any(bad in message.content.lower() for bad in bad_words):
        await message.delete()
        await escalate_punishment(message.channel, message.author, "Use of banned word.")

    if message.mentions and not message.content.strip():
        await escalate_punishment(message.channel, message.author, "Ghost ping")

    if len(message.mentions) >= 5:
        await escalate_punishment(message.channel, message.author, "Mass mentions")

    if "discord.gg/" in message.content.lower():
        await escalate_punishment(message.channel, message.author, "Invite link posting")

    for user in message.mentions:
        status_key = status_store.get(user.id)
        if status_key and status_key in status_messages:
            try:
                reply = await message.channel.send(status_messages[status_key].format(user=user.display_name))
                await asyncio.sleep(5)
                await reply.delete()
            except:
                pass

# Status Commands
@bot.command(name="srn")
async def studying(ctx): status_store[ctx.author.id] = "srn"; await reply_and_delete(ctx, f"📚 | **{ctx.author.display_name}** is now studying."); await update_status_board()
@bot.command(name="b")
async def break_time(ctx): status_store[ctx.author.id] = "b"; await reply_and_delete(ctx, f"☕ | **{ctx.author.display_name}** is taking a short break."); await update_status_board()
@bot.command(name="dl")
async def do_later(ctx): status_store[ctx.author.id] = "dl"; await reply_and_delete(ctx, f"🛠️ | **{ctx.author.display_name}** is busy right now."); await update_status_board()
@bot.command(name="s")
async def sleeping(ctx): status_store[ctx.author.id] = "s"; await reply_and_delete(ctx, f"😴 | **{ctx.author.display_name}** is sleeping."); await update_status_board()
@bot.command(name="f")
async def free(ctx): status_store[ctx.author.id] = "f"; await reply_and_delete(ctx, f"✅ | **{ctx.author.display_name}** is now free!"); await update_status_board()
@bot.command(name="cs")
async def clear_status(ctx):
    if ctx.author.id in status_store:
        del status_store[ctx.author.id]
        await reply_and_delete(ctx, f"🧹 | **{ctx.author.display_name}** status cleared.")
        await update_status_board()
    else:
        await reply_and_delete(ctx, "ℹ️ | You don't have any status set.")
@bot.command(name="status")
async def show_status(ctx): await update_status_board(); await reply_and_delete(ctx, "📊 | Status board updated.")

# Moderation Helpers
async def unauthorized_dm(user, attempted_level):
    msg = f"⚠️ **Notice:** You attempted to use `{attempted_level}` level moderation commands which are not permitted for your role.\nPlease only use commands within your role permissions.\nMisuse may result in demotion or warning.\n\nRefer to `.modhelp` for your access."
    try:
        await user.send(msg)
    except:
        pass

def check_permission(ctx, required_level):
    user_level = mod_level(ctx.author)
    levels = {"trialmod": 1, "mod": 2, "headmod": 3}
    if user_level is None:
        return False
    return levels[user_level] >= levels[required_level]

async def require_level(ctx, level):
    if not check_permission(ctx, level):
        await unauthorized_dm(ctx.author, level)
        return False
    return True

# Moderation Commands
@bot.command()
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    if not await require_level(ctx, "trialmod"): return
    await escalate_punishment(ctx, member, reason)

@bot.command()
async def history(ctx, member: discord.Member):
    if not await require_level(ctx, "trialmod"): return
    user_warns = warns.get(member.id, [])
    msg = f"📜 | {member.mention} warning history:\n" + "\n".join(f"- {r}" for r in user_warns) if user_warns else "✅ | No warnings."
    await ctx.send(msg)

@bot.command()
async def timeout(ctx, member: discord.Member, seconds: int = 300):
    if not await require_level(ctx, "trialmod"): return
    await member.timeout(discord.utils.utcnow() + discord.timedelta(seconds=seconds))
    await ctx.send(f"⏱️ | {member.mention} has been timed out.")

@bot.command()
async def untimeout(ctx, member: discord.Member):
    if not await require_level(ctx, "mod"): return
    await member.timeout(None)
    await ctx.send(f"⏱️ | {member.mention} timeout lifted.")

@bot.command()
async def delwarn(ctx, member: discord.Member):
    if not await require_level(ctx, "mod"): return
    warns.pop(member.id, None)
    await ctx.send(f"🧹 | Cleared warnings for {member.mention}.")

@bot.command()
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    if not await require_level(ctx, "mod"): return
    await member.kick(reason=reason)
    await ctx.send(f"👢 | Kicked {member.mention} for: {reason}")

@bot.command()
async def ban(ctx, member: discord.Member):
    if not await require_level(ctx, "headmod"): return
    ban_role = discord.utils.get(ctx.guild.roles, id=BAN_ROLE_ID)
    await member.add_roles(ban_role)
    await ctx.send(f"🚫 | Soft banned {member.mention} (role applied).")

@bot.command()
async def lock(ctx):
    if not await require_level(ctx, "headmod"): return
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send("🔒 | Channel locked.")

@bot.command()
async def unlock(ctx):
    if not await require_level(ctx, "headmod"): return
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send("🔓 | Channel unlocked.")

@bot.command()
async def purge(ctx, amount: int = 10):
    if not await require_level(ctx, "mod"): return
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 | Cleared {amount} messages.", delete_after=5)

@bot.command()
async def mute(ctx, member: discord.Member):
    if not await require_level(ctx, "trialmod"): return
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not mute_role:
        mute_role = await ctx.guild.create_role(name="Muted")
        for channel in ctx.guild.channels:
            await channel.set_permissions(mute_role, send_messages=False, speak=False)
    await member.add_roles(mute_role)
    await ctx.send(f"🔇 | {member.mention} muted.")

@bot.command()
async def unmute(ctx, member: discord.Member):
    if not await require_level(ctx, "mod"): return
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if mute_role:
        await member.remove_roles(mute_role)
        await ctx.send(f"🔊 | {member.mention} unmuted.")

@bot.command(name="modhelp")
async def modhelp(ctx):
    embed = discord.Embed(title="🛡️ Moderation System Guide", color=discord.Color.gold())
    embed.add_field(name="Trial Mod", value="✅ `.warn`, `.history`, `.timeout`, `.mute`", inline=False)
    embed.add_field(name="Mod", value="✅ All Trial Mod commands + `.kick`, `.untimout`, `.delwarn`, `.purge`, `.unmute`", inline=False)
    embed.add_field(name="Head Mod", value="✅ All Mod commands + `.ban`, `.lock`, `.unlock`", inline=False)
    embed.set_footer(text="Use commands responsibly. Unauthorized use will trigger professional warnings.")
    await ctx.send(embed=embed)

bot.run(TOKEN)
