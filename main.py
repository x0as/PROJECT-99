import os
import discord
from discord.ext import commands
import datetime
import json
import asyncio
import threading
from flask import Flask, jsonify

# --- Load environment variables from .env file FIRST ---
from dotenv import load_dotenv
load_dotenv()

# --- Flask Setup ---
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"message": "Discord Bot is running and connected to API!"})

@app.route('/statuses', methods=['GET'])
def get_statuses_api():
    return jsonify(user_statuses)

@app.route('/status/<user_id>', methods=['GET'])
def get_user_status_api(user_id):
    user_id_str = str(user_id)
    if user_id_str in user_statuses:
        return jsonify(user_statuses[user_id_str])
    return jsonify({"error": "User status not found"}), 404

# --- Global Variables for Firebase ---
app_id = os.environ.get('APP_ID', 'default-app-id')
firebase_config_str = os.environ.get('FIREBASE_CONFIG', '{}')
initial_auth_token = os.environ.get('INITIAL_AUTH_TOKEN', None)
firebase_config = json.loads(firebase_config_str)

FIREBASE_CREDENTIALS_PATH = os.environ.get('FIREBASE_CREDENTIALS_PATH', '') # Set default to empty string if not provided

import firebase_admin
from firebase_admin import credentials, firestore, auth

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True # Essential for fetching member info for status embed

# Define command prefixes. Bot will listen for all of them.
STATUS_COMMAND_PREFIX = '.'
SUGGESTION_COMMAND_PREFIX = '!'

bot = commands.Bot(command_prefix=commands.when_mentioned_or(STATUS_COMMAND_PREFIX, SUGGESTION_COMMAND_PREFIX), intents=intents)

# --- Firestore Initialization ---
db = None
auth_app = None
current_firebase_user_id = None
user_statuses = {}
status_embed_message_id = None
STATUSES_COLLECTION_PATH = f"artifacts/{app_id}/public/data/user_statuses"
EMBED_INFO_COLLECTION_PATH = f"artifacts/{app_id}/public/data/embed_info"
SUGGESTIONS_COLLECTION_PATH = f"artifacts/{app_id}/public/data/suggestions"

async def initialize_firestore():
    """Initializes Firebase and authenticates the bot."""
    global db, auth_app, current_firebase_user_id
    if firebase_admin._apps:
        print("Firebase Admin SDK already initialized.")
        db = firestore.client()
        auth_app = auth.get_auth()
        return

    try:
        if FIREBASE_CREDENTIALS_PATH and os.path.exists(FIREBASE_CREDENTIALS_PATH):
            cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
            firebase_admin.initialize_app(cred, firebase_config)
            print("Firebase Admin SDK initialized using service account file.")
        else:
            # Fallback for dummy/anonymous initialization if no valid path
            print(f"Firebase credentials file not found or path not set: {FIREBASE_CREDENTIALS_PATH}. Initializing with dummy/anonymous.")
            dummy_cred = credentials.Certificate({
                "private_key_id": "dummy",
                "private_key": "dummy",
                "client_email": "dummy",
                "client_id": "dummy",
                "type": "service_account"
            })
            firebase_admin.initialize_app(dummy_cred, firebase_config)
            print("Firebase Admin SDK initialized with dummy credentials.")

    except Exception as e:
        print(f"Error initializing Firebase Admin SDK: {e}")
        return # Do not proceed if initialization fails

    db = firestore.client()
    auth_app = auth.get_auth()
    try:
        if initial_auth_token:
            decoded_token = auth_app.verify_id_token(initial_auth_token)
            current_firebase_user_id = decoded_token['uid']
            print(f"Firebase authenticated with custom token for user: {current_firebase_user_id}")
        else:
            current_firebase_user_id = "anonymous_bot_user"
            print(f"Firebase operating as anonymous user (no initial auth token provided or valid).")
    except Exception as e:
        print(f"Error during Firebase authentication: {e}. Operating as anonymous user.")
        current_firebase_user_id = "anonymous_bot_user_error"


# --- Firestore Helper Functions ---
async def get_all_user_statuses():
    if not db:
        print("Firestore not initialized, cannot fetch statuses.")
        return {}
    try:
        doc_ref = db.collection(STATUSES_COLLECTION_PATH).document('current_statuses')
        doc = await asyncio.to_thread(doc_ref.get)
        return doc.to_dict() if doc.exists else {}
    except Exception as e:
        print(f"Error fetching user statuses from Firestore: {e}")
        return {}

async def set_all_user_statuses(statuses_data):
    if not db:
        print("Firestore not initialized, cannot save statuses.")
        return
    try:
        doc_ref = db.collection(STATUSES_COLLECTION_PATH).document('current_statuses')
        await asyncio.to_thread(doc_ref.set, statuses_data)
        print("User statuses saved to Firestore.")
    except Exception as e:
        print(f"Error saving user statuses to Firestore: {e}")

async def get_status_embed_message_id():
    if not db:
        print("Firestore not initialized, cannot fetch embed message ID.")
        return None
    try:
        doc_ref = db.collection(EMBED_INFO_COLLECTION_PATH).document('status_embed')
        doc = await asyncio.to_thread(doc_ref.get)
        return doc.to_dict().get('message_id') if doc.exists else None
    except Exception as e:
        print(f"Error fetching status embed message ID from Firestore: {e}")
        return None

async def set_status_embed_message_id(message_id):
    if not db:
        print("Firestore not initialized, cannot save embed message ID.")
        return
    try:
        doc_ref = db.collection(EMBED_INFO_COLLECTION_PATH).document('status_embed')
        await asyncio.to_thread(doc_ref.set, {'message_id': message_id})
        print(f"Status embed message ID saved: {message_id}")
    except Exception as e:
        print(f"Error saving status embed message ID to Firestore: {e}")

async def save_suggestion_to_firestore(suggestion_data):
    if not db:
        print("Firestore not initialized, cannot save suggestion.")
        return
    try:
        await asyncio.to_thread(db.collection(SUGGESTIONS_COLLECTION_PATH).add, suggestion_data)
        print("Suggestion saved to Firestore.")
    except Exception as e:
        print(f"Error saving suggestion to Firestore: {e}")

# --- Embed Management ---
STATUS_CHANNEL_ID = 1375511813713821727 # Replace with your actual status channel ID
SUGGESTION_CHANNEL_ID = 1375094650003521636 # Replace with your actual suggestion channel ID

def create_status_embed():
    embed = discord.Embed(
        title=":hastag~1: Member Status Board ✨",
        description="Here's what everyone's up to right now!",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url="https://placehold.co/100x100/ADD8E6/000000?text=Status")
    sorted_statuses = sorted(user_statuses.items(), key=lambda item: item[1].get('timestamp', ''))
    if not sorted_statuses:
        embed.add_field(name="No statuses yet!", value=f"Use a command like `{STATUS_COMMAND_PREFIX}f` to set your status.", inline=False)
    else:
        for user_id_str, status_info in sorted_statuses:
            status_text = status_info.get('status', 'Unknown')
            timestamp_str = status_info.get('timestamp', 'N/A')
            
            # Fetch user object (requires members intent and bot being in guild)
            # This might require bot to be in the guild where the user is
            user = bot.get_user(int(user_id_str)) # Tries to get from cache first
            if user is None:
                # If user not in cache, try to fetch from any guild the bot is in
                for guild in bot.guilds:
                    user = guild.get_member(int(user_id_str))
                    if user:
                        break # Found the user in a guild
            
            user_display_name = user.display_name if user else f"User ID: {user_id_str}"
            
            # Use Discord's built-in time formatting for relative timestamps
            try:
                dt_object_utc = datetime.datetime.fromisoformat(timestamp_str)
                if dt_object_utc.tzinfo is None:
                    dt_object_utc = dt_object_utc.replace(tzinfo=datetime.timezone.utc)
                unix_timestamp = int(dt_object_utc.timestamp())
                display_time_discord = f"<t:{unix_timestamp}:R>"
            except ValueError:
                display_time_discord = timestamp_str # Fallback if parsing fails

            embed.add_field(
                name=f"👤 {user_display_name}",
                value=f"Status: **{status_text}**\nUpdated: {display_time_discord}",
                inline=False
            )
    embed.set_footer(text=f"Last updated: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
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
            try:
                message = await channel.fetch_message(status_embed_message_id)
                await message.edit(embed=embed)
                print(f"Status embed updated in channel {channel.name}.")
            except discord.NotFound:
                print("Old status embed message not found, sending a new one.")
                new_message = await channel.send(embed=embed)
                status_embed_message_id = new_message.id
                await set_status_embed_message_id(new_message.id)
                print(f"New status embed sent and ID saved in channel {channel.name}.")
        else:
            new_message = await channel.send(embed=embed)
            status_embed_message_id = new_message.id
            await set_status_embed_message_id(new_message.id)
            print(f"New status embed sent in channel {channel.name}.")
    except discord.Forbidden:
        print(f"Bot lacks permissions (read messages, send messages, embed links, manage messages) in channel {channel.name}.")
        # Provide specific permissions required in the error for easier debugging
        await channel.send("I need permissions to `Read Messages`, `Send Messages`, `Embed Links`, and `Manage Messages` to update the status board!", delete_after=15)
    except Exception as e:
        print(f"Critical error updating/sending status embed: {e}")

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

    # Handle status mention responses
    if message.mentions:
        for user_mentioned in message.mentions:
            if user_mentioned == bot.user: # Don't respond if bot is mentioned
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
                    print(f"Bot lacks permissions to send/delete messages in {message.channel.name}")
                except Exception as e:
                    print(f"Error sending mention response: {e}")

    # Process commands using the bot's built-in command handler
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # Check if the message starts with ANY of the prefixes to give a "command not found" message
        if ctx.message.content.startswith(STATUS_COMMAND_PREFIX) or \
           ctx.message.content.startswith(SUGGESTION_COMMAND_PREFIX) or \
           ctx.message.content.startswith(bot.user.mention): # Also if bot was mentioned but command not found
            await ctx.send(f"That command doesn't exist! Use `{STATUS_COMMAND_PREFIX}statushelp` or `{SUGGESTION_COMMAND_PREFIX}suggesthelp`.", delete_after=8)
        return # Do not spam for every non-command message
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing argument. Please check the command syntax. Example: `{ctx.prefix}{ctx.command.name} <argument>`", delete_after=8)
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"Invalid argument. Please provide valid input.", delete_after=8)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"Command on cooldown. Try again in {error.retry_after:.2f} seconds.", delete_after=8)
    elif isinstance(error, commands.MissingPermissions) or isinstance(error, commands.BotMissingPermissions):
        await ctx.send("I don't have the necessary permissions for that or you don't.", delete_after=8)
    else:
        print(f"Unhandled command error in {ctx.command}: {error} (Type: {type(error)})")
        await ctx.send(f"An unexpected error occurred: `{error}`", delete_after=8)


# --- Status Commands ---
async def process_status_command(ctx, status_text, creative_response):
    """Helper function to set status and send responses."""
    try:
        # Delete user's command message
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
    await update_status_embed() # Update the embed after status change
    try:
        bot_response = await ctx.send(creative_response)
        await bot_response.delete(delay=8)
    except discord.Forbidden:
        print(f"Bot lacks permissions to send/delete messages in {ctx.channel.name}")
    except Exception as e:
        print(f"Error sending/deleting bot response: {e}")

@bot.command(name='dl', aliases=['do_later'])
async def do_later(ctx):
    await process_status_command(ctx, "Do Later", "Task marked for later. Focus on now! 🚧")

@bot.command(name='s', aliases=['sleep'])
async def sleeping(ctx):
    await process_status_command(ctx, "Sleeping", "You're in dreamland. We'll keep it quiet. 😴")

@bot.command(name='f', aliases=['free'])
async def free(ctx):
    await process_status_command(ctx, "Free", "Ready for action! Let’s go! ✅")

@bot.command(name='srn', aliases=['studying'])
async def studying_right_now(ctx):
    await process_status_command(ctx, "Studying Right Now", "Deep in study mode! Keep it up! 📚")

@bot.command(name='o', aliases=['out'])
async def outside(ctx):
    await process_status_command(ctx, "Outside", "Enjoy the outdoors! We'll catch you later. 🚶‍♂️")

@bot.command(name='b', aliases=['break'])
async def on_break(ctx):
    await process_status_command(ctx, "On Break", "Time to recharge! See you soon. ☕")

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
            dt_object_utc = datetime.datetime.fromisoformat(timestamp_str)
            if dt_object_utc.tzinfo is None:
                dt_object_utc = dt_object_utc.replace(tzinfo=datetime.timezone.utc)
            unix_timestamp = int(dt_object_utc.timestamp())
            display_time_discord = f"<t:{unix_timestamp}:R>"
        except ValueError:
            display_time_discord = timestamp_str # Fallback if parsing fails

        response = f"Your status: **{status_text}** (Updated: {display_time_discord})"
    else:
        response = f"No status set. Use `{STATUS_COMMAND_PREFIX}f`, `{STATUS_COMMAND_PREFIX}s`, etc., to set one!"
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
            f"`{STATUS_COMMAND_PREFIX}f` - Set status to 'Free'\n"
            f"`{STATUS_COMMAND_PREFIX}s` - Set status to 'Sleeping'\n"
            f"`{STATUS_COMMAND_PREFIX}dl` - Set status to 'Do Later'\n"
            f"`{STATUS_COMMAND_PREFIX}srn` - Set status to 'Studying Right Now'\n"
            f"`{STATUS_COMMAND_PREFIX}o` - Set status to 'Outside'\n"
            f"`{STATUS_COMMAND_PREFIX}b` - Set status to 'On Break'\n"
            f"`{STATUS_COMMAND_PREFIX}clearstatus` - Clear your status\n"
            f"`{STATUS_COMMAND_PREFIX}status` - Show your current status\n"
            f"`{STATUS_COMMAND_PREFIX}statushelp` - Show this help message"
        ),
        inline=False
    )
    try:
        await ctx.send(embed=help_embed)
    except discord.Forbidden:
        print(f"Bot lacks permissions to send messages in {ctx.channel.name}")
    except Exception as e:
        print(f"Error sending help embed: {e}")

# --- Suggestion System Commands ---
@bot.command(name='suggest')
async def submit_suggestion(ctx, *, suggestion: str):
    """Allows users to submit a suggestion."""
    if not suggestion:
        try:
            await ctx.send(f"Please provide a suggestion! Usage: `{SUGGESTION_COMMAND_PREFIX}suggest <your suggestion here>`", delete_after=8)
            await ctx.message.delete(delay=5)
        except Exception as e:
            print(f"Error responding to empty suggestion or deleting message: {e}")
        return

    suggestion_data = {
        'author_id': str(ctx.author.id),
        'author_name': ctx.author.display_name,
        'suggestion_text': suggestion,
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    await save_suggestion_to_firestore(suggestion_data)

    # Notify staff channel
    suggestion_channel = bot.get_channel(SUGGESTION_CHANNEL_ID)
    if suggestion_channel:
        embed = discord.Embed(
            title="💡 New Suggestion Received! 💡",
            description=f"**Submitted by:** {ctx.author.mention}\n\n**Suggestion:**\n{suggestion}",
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_footer(text=f"User ID: {ctx.author.id}")
        try:
            await suggestion_channel.send(embed=embed)
            print(f"Suggestion from {ctx.author.display_name} sent to staff channel.")
        except discord.Forbidden:
            print(f"Bot lacks permissions to send messages in suggestion channel {SUGGESTION_CHANNEL_ID}.")
        except Exception as e:
            print(f"Error sending suggestion embed to staff channel: {e}")
    else:
        print(f"Suggestion channel with ID {SUGGESTION_CHANNEL_ID} not found.")

    # User confirmation in channel (auto-delete)
    try:
        confirm_message = await ctx.send(f"✅ Your suggestion has been submitted, {ctx.author.mention}! Thank you for your input. We've notified the staff.")
        await ctx.message.delete(delay=5) # Delete user's command message
        await confirm_message.delete(delay=5)
    except discord.Forbidden:
        print(f"Bot lacks permissions to send/delete messages in {ctx.channel.name}.")
    except Exception as e:
        print(f"Error sending/deleting user confirmation in channel: {e}")

    # User confirmation via DM
    try:
        dm_embed = discord.Embed(
            title="Suggestion Confirmation",
            description="Thank you for your suggestion! We've received it and appreciate your input.",
            color=discord.Color.green()
        )
        dm_embed.add_field(name="Your Suggestion:", value=suggestion, inline=False)
        dm_embed.add_field(name="Submitted At:", value=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), inline=False)
        await ctx.author.send(embed=dm_embed)
        print(f"Suggestion confirmation sent to {ctx.author.display_name} via DM.")
    except discord.Forbidden:
        print(f"Could not DM {ctx.author.display_name}. They might have DMs disabled or the bot is blocked.")
    except Exception as e:
        print(f"Error sending DM confirmation: {e}")

@bot.command(name='suggesthelp')
async def suggest_help(ctx):
    """Provides help for the suggestion system."""
    try:
        await ctx.message.delete(delay=5)
    except discord.Forbidden:
        print(f"Bot lacks permissions to delete messages in {ctx.channel.name}")
    except Exception as e:
        print(f"Error deleting user message: {e}")

    help_embed = discord.Embed(
        title="💡 Suggestion System Help 💡",
        description="Here's how you can submit your ideas and feedback!",
        color=discord.Color.purple()
    )
    help_embed.set_thumbnail(url="https://placehold.co/100x100/D8BFD8/000000?text=Suggest")
    help_embed.add_field(
        name="How to Submit a Suggestion:",
        value=f"Use the command `{SUGGESTION_COMMAND_PREFIX}suggest <your suggestion here>`.\n\n"
              f"**Example:** `{SUGGESTION_COMMAND_PREFIX}suggest Add a new channel for game discussions.`",
        inline=False
    )
    help_embed.add_field(
        name="What Happens Next?",
        value="Your suggestion will be sent to the staff team for review. You'll receive a confirmation message in the channel and a DM.",
        inline=False
    )
    help_embed.set_footer(text="Thank you for helping us improve!")
    try:
        await ctx.send(embed=help_embed)
    except discord.Forbidden:
        print(f"Bot lacks permissions to send messages in {ctx.channel.name}")
    except Exception as e:
        print(f"Error sending suggestion help embed: {e}")

# --- Run Flask and Discord Bot ---
def run_flask():
    """Run Flask app in a separate thread."""
    # This conditional ensures app.run() is only called once and not in debug mode
    # where Flask's own reloader might conflict with threading.
    if not app.debug and not app.testing and not threading.current_thread().name == 'MainThread':
        print("Starting Flask server...")
        # Use_reloader=False is important when running Flask in a separate thread
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    else:
        # In __main__ block, the main thread will handle the bot.start()
        # Flask is implicitly started by the Discord bot's main loop if not threaded
        pass

async def main():
    """Main function to start both Flask and Discord bot."""
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("Flask server thread initiated.")

    # Start Discord bot
    try:
        discord_token = os.environ.get('DISCORD_BOT_TOKEN')
        if not discord_token:
            raise ValueError("DISCORD_BOT_TOKEN environment variable not set. Please check your .env file and ensure it's loaded.")

        await bot.start(discord_token)
    except Exception as e:
        print(f"Error starting Discord bot: {e}")

if __name__ == '__main__':
    asyncio.run(main())
