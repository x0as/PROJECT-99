import os
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
