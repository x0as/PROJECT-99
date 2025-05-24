import discord
from discord.ext import commands, tasks
import asyncio
import os

TOKEN = os.getenv('TOKEN')
STATUS_CHANNEL_ID = 1372938839164981289

HEADMOD_ID = 1368125926600212531
MOD_ID = 1344657921556086875import os
import discord
from discord.ext import commands
import datetime
import json
import asyncio
import threading
from flask import Flask
import firebase_admin
from firebase_admin import credentials, firestore, auth

# --- Flask Setup ---
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"message": "Discord Bot is running!"})

@app.route('/statuses', methods=['GET'])
def get_statuses():
    """API endpoint to retrieve all user statuses."""
    return jsonify(user_statuses)

@app.route('/status/<user_id>', methods=['GET'])
def get_user_status(user_id):
    """API endpoint to retrieve a specific user's status."""
    user_id_str = str(user_id)
    if user_id_str in user_statuses:
        return jsonify(user_statuses[user_id_str])
    return jsonify({"error": "User status not found"}), 404

# --- Global Variables for Firebase ---
app_id = os.environ.get('__app_id', 'default-app-id')
firebase_config_str = os.environ.get('__firebase_config', '{}')
initial_auth_token = os.environ.get('__initial_auth_token', None)
firebase_config = json.loads(firebase_config_str)

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='.', intents=intents)

# --- Firestore Initialization ---
db = None
auth_app = None
user_id = None
user_statuses = {}
status_embed_message_id = None
STATUSES_COLLECTION_PATH = f"artifacts/{app_id}/public/data/user_statuses"
EMBED_INFO_COLLECTION_PATH = f"artifacts/{app_id}/public/data/embed_info"

async def initialize_firestore():
    """Initializes Firebase and authenticates the bot."""
    global db, auth_app, user_id
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate({
                "private_key_id": "dummy",
                "private_key": "dummy",
                "client_email": "dummy",
                "client_id": "dummy",
                "type": "service_account"
            })
            firebase_admin.initialize_app(cred, firebase_config)
            print("Firebase Admin SDK initialized.")
        except Exception as e:
            print(f"Error initializing Firebase Admin SDK: {e}")
            pass
    db = firestore.client()
    auth_app = auth.get_auth()
    try:
        if initial_auth_token:
            decoded_token = auth_app.verify_id_token(initial_auth_token)
            user_id = decoded_token['uid']
            print(f"Firebase authenticated with custom token for user: {user_id}")
        else:
            user_id = "anonymous_bot_user"
            print(f"Firebase operating as anonymous user: {user_id}")
    except Exception as e:
        print(f"Error during Firebase authentication: {e}")
        user_id = "anonymous_bot_user_error"
        print(f"Firebase operating as anonymous user due to auth error: {user_id}")

# --- Firestore Helper Functions ---
async def get_all_user_statuses():
    if not db:
        print("Firestore not initialized.")
        return {}
    try:
        doc_ref = db.collection(STATUSES_COLLECTION_PATH).document('current_statuses')
        doc = await asyncio.to_thread(doc_ref.get)
        return doc.to_dict() if doc.exists else {}
    except Exception as e:
        print(f"Error fetching user statuses: {e}")
        return {}

async def set_all_user_statuses(statuses_data):
    if not db:
        print("Firestore not initialized.")
        return
    try:
        doc_ref = db.collection(STATUSES_COLLECTION_PATH).document('current_statuses')
        await asyncio.to_thread(doc_ref.set, statuses_data)
        print("User statuses saved to Firestore.")
    except Exception as e:
        print(f"Error saving user statuses: {e}")

async def get_status_embed_message_id():
    if not db:
        print("Firestore not initialized.")
        return None
    try:
        doc_ref = db.collection(EMBED_INFO_COLLECTION_PATH).document('status_embed')
        doc = await asyncio.to_thread(doc_ref.get)
        return doc.to_dict().get('message_id') if doc.exists else None
    except Exception as e:
        print(f"Error fetching status embed message ID: {e}")
        return None

async def set_status_embed_message_id(message_id):
    if not db:
        print("Firestore not initialized.")
        return
    try:
        doc_ref = db.collection(EMBED_INFO_COLLECTION_PATH).document('status_embed')
        await asyncio.to_thread(doc_ref.set, {'message_id': message_id})
        print(f"Status embed message ID saved: {message_id}")
    except Exception as e:
        print(f"Error saving status embed message ID: {e}")

# --- Embed Management ---
STATUS_CHANNEL_ID = 1375511813713821727

def create_status_embed():
    embed = discord.Embed(
        title=":hastag~1:  Member Status Board ✨",
        description="Here's what everyone's up to right now!",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url="https://placehold.co/100x100/ADD8E6/000000?text=Status")
    sorted_statuses = sorted(user_statuses.items(), key=lambda item: item[1].get('timestamp', ''))
    if not sorted_statuses:
        embed.add_field(name="No statuses yet!", value="Use a command like `.f` to set your status.", inline=False)
    else:
        for user_id_str, status_info in sorted_statuses:
            status_text = status_info.get('status', 'Unknown')
            timestamp_str = status_info.get('timestamp', 'N/A')
            try:
                dt_object = datetime.datetime.fromisoformat(timestamp_str)
                display_time = dt_object.strftime("%Y-%m-%d %H:%M:%S UTC")
            except ValueError:
                display_time = timestamp_str
            user = bot.get_user(int(user_id_str))
            user_display_name = user.display_name if user else f"User ID: {user_id_str}"
            embed.add_field(
                name=f"👤 {user_display_name}",
                value=f"Status: **{status_text}**\nUpdated: <t:{int(datetime.datetime.now().timestamp())}:R>",
                inline=False
            )
    embed.set_footer(text=f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    return embed

async def update_status_embed():
    global status_embed_message_id
    channel = bot.get_channel(STATUS_CHANNEL_ID)
    if not channel:
        print(f"Error: Status channel with ID {STATUS_CHANNEL_ID} not found.")
        return
    embed = create_status_embed()
    try:
        if status_embed_message_id:
            message = await channel.fetch_message(status_embed_message_id)
            await message.edit(embed=embed)
            print(f"Status embed updated in channel {channel.name}.")
        else:
            new_message = await channel.send(embed=embed)
            status_embed_message_id = new_message.id
            await set_status_embed_message_id(new_message.id)
            print(f"New status embed sent in channel {channel.name}.")
    except discord.Forbidden:
        print(f"Bot lacks permissions in channel {channel.name}.")
    except Exception as e:
        print(f"Error updating/sending status embed: {e}")

# --- Bot Events ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    await initialize_firestore()
    global user_statuses, status_embed_message_id
    user_statuses = await get_all_user_statuses()
    status_embed_message_id = await get_status_embed_message_id()
    await update_status_embed()
    print("Bot is ready and status embed is initialized/updated.")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.mentions:
        for user_mentioned in message.mentions:
            if user_mentioned == bot.user:
                continue
            user_id_str = str(user_mentioned.id)
            if user_id_str in user_statuses:
                status_info = user_statuses[user_id_str]
                status_text = status_info.get('status', 'Unknown')
                responses = {
                    "Do Later": f"Hey! {user_mentioned.display_name} is busy and will get to it later. 🚧",
                    "Sleeping": f"Shhh! {user_mentioned.display_name} is sleeping. 😴",
                    "Free": f"Good news! {user_mentioned.display_name} is free! ✅",
                    "Studying Right Now": f"{user_mentioned.display_name} is studying right now. 📚",
                    "Outside": f"{user_mentioned.display_name} is outside and will see your message later. 🚶‍♂️",
                    "On Break": f"{user_mentioned.display_name} is on a break. ☕"
                }
                response_message_text = responses.get(status_text, f"{user_mentioned.display_name}'s status: '{status_text}'.")
                try:
                    bot_reply = await message.channel.send(response_message_text, reference=message)
                    await bot_reply.delete(delay=8)
                except discord.Forbidden:
                    print(f"Bot lacks permissions to send messages in {message.channel.name}")
                except Exception as e:
                    print(f"Error sending mention response: {e}")
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing argument. Check the command syntax.", delete_after=8)
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"Invalid argument. Please provide valid input.", delete_after=8)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"Command on cooldown. Try again in {error.retry_after:.2f} seconds.", delete_after=8)
    else:
        print(f"Unhandled command error: {error}")
        await ctx.send(f"Error: {error}", delete_after=8)

# --- Status Commands ---
async def set_user_status(ctx, status_text, creative_response):
    try:
        await ctx.message.delete(delay=5)
    except discord.Forbidden:
        print(f"Bot lacks permissions to delete messages in {ctx.channel.name}")
    except Exception as e:
        print(f"Error deleting user message: {e}")
    user_id_str = str(ctx.author.id)
    user_statuses[user_id_str] = {
        'status': status_text,
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    await set_all_user_statuses(user_statuses)
    await update_status_embed()
    try:
        bot_response = await ctx.send(creative_response)
        await bot_response.delete(delay=8)
    except discord.Forbidden:
        print(f"Bot lacks permissions to send/delete messages in {ctx.channel.name}")
    except Exception as e:
        print(f"Error sending/deleting bot response: {e}")

@bot.command(name='dl')
async def do_later(ctx):
    await set_user_status(ctx, "Do Later", "Task marked for later. Focus on now! 🚧")

@bot.command(name='s')
async def sleeping(ctx):
    await set_user_status(ctx, "Sleeping", "You're in dreamland. We'll keep it quiet. 😴")

@bot.command(name='f')
async def free(ctx):
    await set_user_status(ctx, "Free", "Ready for action! Let’s go! ✅")

@bot.command(name='srn')
async def studying_right_now(ctx):
    await set_user_status(ctx, "Studying Right Now", "Deep in study mode! Keep it up! 📚")

@bot.command(name='o')
async def outside(ctx):
    await set_user_status(ctx, "Outside", "Enjoy the outdoors! We'll catch you later. 🚶‍♂️")

@bot.command(name='b')
async def on_break(ctx):
    await set_user_status(ctx, "On Break", "Time to recharge! See you soon. ☕")

@bot.command(name='clearstatus')
async def clear_status(ctx):
    try:
        await ctx.message.delete(delay=5)
    except discord.Forbidden:
        print(f"Bot lacks permissions to delete messages in {ctx.channel.name}")
    except Exception as e:
        print(f"Error deleting user message: {e}")
    user_id_str = str(ctx.author.id)
    if user_id_str in user_statuses:
        del user_statuses[user_id_str]
        await set_all_user_statuses(user_statuses)
        await update_status_embed()
        try:
            bot_response = await ctx.send("Your status has been cleared! 🤔")
            await bot_response.delete(delay=8)
        except discord.Forbidden:
            print(f"Bot lacks permissions to send/delete messages in {ctx.channel.name}")
        except Exception as e:
            print(f"Error sending/deleting bot response: {e}")
    else:
        try:
            bot_response = await ctx.send("No status to clear! 🤔")
            await bot_response.delete(delay=8)
        except discord.Forbidden:
            print(f"Bot lacks permissions to send/delete messages in {ctx.channel.name}")
        except Exception as e:
            print(f"Error sending/deleting bot response: {e}")

@bot.command(name='status')
async def show_status(ctx):
    try:
        await ctx.message.delete(delay=5)
    except discord.Forbidden:
        print(f"Bot lacks permissions to delete messages in {ctx.channel.name}")
    except Exception as e:
        print(f"Error deleting user message: {e}")
    user_id_str = str(ctx.author.id)
    if user_id_str in user_statuses:
        status_info = user_statuses[user_id_str]
        status_text = status_info.get('status', 'Unknown')
        timestamp_str = status_info.get('timestamp', 'N/A')
        try:
            dt_object = datetime.datetime.fromisoformat(timestamp_str)
            display_time = dt_object.strftime("%Y-%m-%d %H:%M:%S UTC")
        except ValueError:
            display_time = timestamp_str
        response = f"Your status: **{status_text}** (Updated: <t:{int(datetime.datetime.now().timestamp())}:R>)"
    else:
        response = "No status set. Use `.f`, `.s`, etc., to set one!"
    try:
        bot_response = await ctx.send(response)
        await bot_response.delete(delay=8)
    except discord.Forbidden:
        print(f"Bot lacks permissions to send/delete messages in {ctx.channel.name}")
    except Exception as e:
        print(f"Error sending/deleting bot response: {e}")

@bot.command(name='statushelp')
async def status_help(ctx):
    try:
        await ctx.message.delete(delay=5)
    except discord.Forbidden:
        print(f"Bot lacks permissions to delete messages in {ctx.channel.name}")
    except Exception as e:
        print(f"Error deleting user message: {e}")
    help_embed = discord.Embed(
        title="📚 Status System Help 📚",
        description="Quick guide to managing your availability!",
        color=discord.Color.green()
    )
    help_embed.set_thumbnail(url="https://placehold.co/100x100/A0D9B1/000000?text=Help")
    help_embed.add_field(
        name="How it Works:",
        value=f"Your status shows on the **Member Status Board** in <#{STATUS_CHANNEL_ID}> and updates instantly.",
        inline=False
    )
    help_embed.add_field(
        name="Commands:",
        value=(
            "`.f` - Set status to 'Free'\n"
            "`.s` - Set status to 'Sleeping'\n"
            "`.dl` - Set status to 'Do Later'\n"
            "`.srn` - Set status to 'Studying Right Now'\n"
            "`.o` - Set status to 'Outside'\n"
            "`.b` - Set status to 'On Break'\n"
            "`.clearstatus` - Clear your status\n"
            "`.status` - Show your current status\n"
            "`.statushelp` - Show this help message"
        ),
        inline=False
    )
    try:
        await ctx.send(embed=help_embed)
    except discord.Forbidden:
        print(f"Bot lacks permissions to send messages in {ctx.channel.name}")
    except Exception as e:
        print(f"Error sending help embed: {e}")

# --- Run Flask and Discord Bot ---
def run_flask():
    """Run Flask app in a separate thread."""
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

async def main():
    """Main function to start both Flask and Discord bot."""
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("Flask server started on http://0.0.0.0:5000")

    # Start Discord bot
    try:
        discord_token = os.environ.get('DISCORD_BOT_TOKEN')
        if not discord_token:
            raise ValueError("DISCORD_BOT_TOKEN environment variable not set.")
        await bot.start(discord_token)
    except Exception as e:
        print(f"Error starting Discord bot: {e}")

if __name__ == '__main__':
    # Run the async main function
    asyncio.run(main())
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
