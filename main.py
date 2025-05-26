import os
import discord
from discord.ext import commands
import datetime
import asyncio
import threading
import random
from flask import Flask, jsonify
from dotenv import load_dotenv

# --- Load environment variables ---
load_dotenv()

# --- Flask Setup (for basic web server) ---
app = Flask(__name__)

# --- Global Variables for In-Memory Storage ---
user_statuses = {}   # Stores user statuses: {user_id_str: {'status': 'Free', 'timestamp': 'ISO_FORMAT_DATETIME'}}
suggestions = {}     # Stores suggestions: {index: {data...}} using a simple counter as key
status_embed_message_id = None  # Stores the message ID of the status board embed
suggestion_counter = 0  # Simple counter to track suggestions (instead of UUID)

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

# Define command prefixes
STATUS_COMMAND_PREFIX = '.'
SUGGESTION_COMMAND_PREFIX = '!'

bot = commands.Bot(command_prefix=commands.when_mentioned_or(STATUS_COMMAND_PREFIX, SUGGESTION_COMMAND_PREFIX), intents=intents)

# --- Channel and Role IDs (REPLACE THESE WITH YOUR ACTUAL IDs) ---
STATUS_CHANNEL_ID = 1375511813713821727           # Status Board Channel
GUIDE_CHANNEL_ID = 1376473911717400598           # Guide Channel where users submit suggestions
SUGGESTION_CHANNEL_ID = 1375094650003521636       # Main channel where suggestions are displayed
SUGGESTION_LOG_CHANNEL_ID = 1375094650003521637   # Channel for logging suggestion actions

# Role IDs for staff who can approve/reject/implement suggestions and set others' statuses
STAFF_ROLE_IDS = [
    1374320995942404215,  # 'Staff' or 'Moderator' Role ID
    987654321098765432    # Another staff role ID if needed
]

# Role ID for Server Designer (REPLACE WITH ACTUAL ID)
SERVER_DESIGNER_ROLE_ID = 123456789012345678  # Placeholder - Replace with your Server Designer role ID

# Role IDs for users who can vote on suggestions. Set to [] if @everyone can vote
VOTER_ROLE_IDS = []  # Example: [123456789012345678] for a 'Member' role

# --- In-Memory Data Management Helpers ---
async def get_all_user_statuses_in_memory():
    return user_statuses

async def set_all_user_statuses_in_memory(statuses_data):
    global user_statuses
    user_statuses = statuses_data

async def get_status_embed_message_id_in_memory():
    return status_embed_message_id

async def set_status_embed_message_id_in_memory(message_id):
    global status_embed_message_id
    status_embed_message_id = message_id

async def save_suggestion_in_memory(suggestion_data):
    global suggestion_counter
    suggestion_counter += 1
    suggestions[suggestion_counter] = suggestion_data
    return suggestion_counter

async def get_suggestion_from_memory(suggestion_index: int):
    data = suggestions.get(suggestion_index)
    if data:
        return {**data, 'index': suggestion_index}
    return None

async def update_suggestion_in_memory(suggestion_index: int, updates: dict):
    if suggestion_index in suggestions:
        suggestions[suggestion_index].update(updates)
        return True
    return False

# --- Helper Functions for Permissions ---
async def is_staff(user: discord.Member):
    if user.guild_permissions.administrator:
        return True
    return any(role.id in STAFF_ROLE_IDS for role in user.roles)

async def can_manage_suggestion(user: discord.Member):
    # Check if user has Administrator permission or Server Designer role
    if user.guild_permissions.administrator:
        return True
    return any(role.id == SERVER_DESIGNER_ROLE_ID for role in user.roles)

async def log_suggestion_action(suggestion_index: int, moderator: discord.Member, action: str, reason: str = None):
    log_channel = bot.get_channel(SUGGESTION_LOG_CHANNEL_ID)
    if not log_channel:
        print(f"Log channel {SUGGESTION_LOG_CHANNEL_ID} not found.")
        return

    log_embed = discord.Embed(
        title=f"📝 Suggestion Log",
        description=f"**Action:** {action.capitalize()}\n"
                    f"**Moderator:** {moderator.mention} ({moderator.display_name})\n"
                    f"**Timestamp:** {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        color=discord.Color.blue()
    )
    if reason:
        log_embed.add_field(name="Reason", value=reason, inline=False)

    try:
        await log_channel.send(embed=log_embed)
    except discord.Forbidden:
        print(f"Bot lacks permissions to send messages in log channel {SUGGESTION_LOG_CHANNEL_ID}.")

async def notify_suggestion_author(author: discord.Member, status: str, suggestion_text: str, reason: str = None):
    if not author:
        return

    if status == "Rejected":
        motivational_messages = [
            (
                f"🌟 **Hey {author.display_name}, your suggestion was reviewed!** 🌟\n"
                f"This time, your idea *'{suggestion_text}'* didn’t make the cut, but don’t let that dim your spark! ✨ "
                f"We believe in your creativity—think even bigger, dream bolder, and your next suggestion might just be the one that lights up The Resource Repository! 🚀 "
                f"Let’s work together to take our community to the next level. 💡"
            ),
            (
                f"💭 **Hi {author.display_name}, we’ve looked at your suggestion!** 💭\n"
                f"Although *'{suggestion_text}'* was rejected this time, your passion for improving The Resource Repository shines through! 🌟 "
                f"Keep brainstorming those creative ideas—your next suggestion could be the key to unlocking our community’s full potential! 🔑 "
                f"Let’s keep pushing the boundaries together! 🚀"
            )
        ]
        message_content = random.choice(motivational_messages)
        if reason:
            message_content += f"\n\n**Reason for Rejection:** {reason}"

        dm_embed = discord.Embed(
            title="💌 Suggestion Update",
            description=message_content,
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        dm_embed.set_footer(text="Thank you for contributing to The Resource Repository!")
    elif status == "Approved":
        approval_messages = [
            (
                f"🎉 **Fantastic news, {author.display_name}!** 🎉\n"
                f"Your suggestion *'{suggestion_text}'* has been **Approved** by the team! 🌟 "
                f"Your brilliant idea is set to make The Resource Repository even better. Keep those amazing thoughts coming! 🚀 "
                f"Thank you for helping our community grow! 💡"
            ),
            (
                f"🌟 **Woohoo, {author.display_name}!** 🌟\n"
                f"We’re thrilled to let you know that your suggestion *'{suggestion_text}'* has been **Approved**! 🎊 "
                f"Your creativity is lighting the way for The Resource Repository—let’s keep the momentum going with more awesome ideas! 🚀 "
                f"You’re making a big difference! 💖"
            )
        ]
        message_content = random.choice(approval_messages)

        dm_embed = discord.Embed(
            title="🎉 Suggestion Approved!",
            description=message_content,
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        dm_embed.set_footer(text="Thank you for your contribution!")
    else:  # Implemented
        implementation_messages = [
            (
                f"⚙️ **Exciting update, {author.display_name}!** ⚙️\n"
                f"Your suggestion *'{suggestion_text}'* has been **Implemented**! 🚀 "
                f"The team is already working on bringing your idea to life in The Resource Repository. Join the discussion in the private channel to share more insights! 🌟 "
                f"You’re helping shape our community’s future—amazing work! 💡"
            ),
            (
                f"🚀 **Big news, {author.display_name}!** 🚀\n"
                f"Your suggestion *'{suggestion_text}'* has been **Implemented**! 🎉 "
                f"We’ve created a private channel to discuss the next steps for your brilliant idea in The Resource Repository. Let’s make it even better together! 🌍 "
                f"Your contributions are incredible—keep it up! 💖"
            )
        ]
        message_content = random.choice(implementation_messages)

        dm_embed = discord.Embed(
            title="⚙️ Suggestion Implemented!",
            description=message_content,
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        dm_embed.set_footer(text="Thank you for your contribution!")

    try:
        await author.send(embed=dm_embed)
    except discord.Forbidden:
        print(f"Cannot send DM to {author.display_name} - DMs are disabled.")

# --- Embed Creation Functions ---
def create_status_embed():
    embed = discord.Embed(
        title=":hastag~1: Member Status Board ✨",
        description="Here's what everyone's up to right now!",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url="https://placehold.co/100x100/ADD8E6/000000?text=Status")
    sorted_statuses = sorted(user_statuses.items(), key=lambda item: item[1].get('timestamp', ''))
    if not sorted_statuses:
        embed.add_field(name="No statuses yet!", value=f"Use a command like `{STATUS_COMMAND_PREFIX}f` to set your status, or `{STATUS_COMMAND_PREFIX}f @user` to set another's.", inline=False)
    else:
        for user_id_str, status_info in sorted_statuses:
            status_text = status_info.get('status', 'Unknown')
            timestamp_str = status_info.get('timestamp', 'N/A')
            
            user = bot.get_user(int(user_id_str))
            if user is None:
                for guild in bot.guilds:
                    user = guild.get_member(int(user_id_str))
                    if user: break
            
            user_display_name = user.display_name if user else f"User ID: {user_id_str}"
            
            try:
                dt_object_utc = datetime.datetime.fromisoformat(timestamp_str)
                if dt_object_utc.tzinfo is None:
                    dt_object_utc = dt_object_utc.replace(tzinfo=datetime.timezone.utc)
                unix_timestamp = int(dt_object_utc.timestamp())
                display_time_discord = f"<t:{unix_timestamp}:R>"
            except (ValueError, TypeError):
                display_time_discord = timestamp_str

            embed.add_field(
                name=f"👤 {user_display_name}",
                value=f"Status: **{status_text}**\nUpdated: {display_time_discord}",
                inline=False
            )
    embed.set_footer(text=f"Last updated: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} (Data is in-memory and resets on bot restart)")
    return embed

async def update_status_embed():
    channel = bot.get_channel(STATUS_CHANNEL_ID)
    if not channel:
        print(f"Status channel {STATUS_CHANNEL_ID} not found.")
        return
    embed = create_status_embed()
    try:
        if status_embed_message_id:
            try:
                message = await channel.fetch_message(status_embed_message_id)
                await message.edit(embed=embed)
            except discord.NotFound:
                new_message = await channel.send(embed=embed)
                await set_status_embed_message_id_in_memory(new_message.id)
        else:
            new_message = await channel.send(embed=embed)
            await set_status_embed_message_id_in_memory(new_message.id)
    except discord.Forbidden:
        print(f"Bot lacks permissions to edit messages in status channel {STATUS_CHANNEL_ID}.")

def create_suggestion_embed(suggestion_data):
    author = suggestion_data['author']
    suggestion_text = suggestion_data['suggestion_text']
    status = suggestion_data.get('status', 'Pending')
    upvotes_list = suggestion_data.get('upvotes', [])
    downvotes_list = suggestion_data.get('downvotes', [])
    rejection_reason = suggestion_data.get('rejection_reason', None)

    upvotes = len(upvotes_list)
    downvotes = len(downvotes_list)

    embed = discord.Embed(
        title="💡 New Suggestion",
        color=0xFFA500 if status == 'Pending' else \
              0x00FF00 if status == 'Approved' else \
              0xFF0000 if status == 'Rejected' else \
              0x0000FF if status == 'Implemented' else 0xFFA500,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )

    embed.add_field(name="Suggested By:", value=f"{author.mention}", inline=False)
    embed.add_field(name="Suggestion:", value=suggestion_text, inline=False)
    embed.add_field(name="Status:", value=status, inline=True)
    embed.add_field(name="Votes:", value=f"✅ Upvotes: {upvotes} | ❌ Downvotes: {downvotes}", inline=True)
    if status == 'Rejected' and rejection_reason:
        embed.add_field(name="Reason for Rejection:", value=rejection_reason, inline=False)
    embed.set_footer(text="Use the buttons below to vote or manage this suggestion.")

    return embed

async def update_suggestion_message(suggestion_index: int, suggestion_message_id: int):
    suggestion_channel = bot.get_channel(SUGGESTION_CHANNEL_ID)
    if not suggestion_channel:
        print(f"Suggestion channel {SUGGESTION_CHANNEL_ID} not found.")
        return

    suggestion_data = await get_suggestion_from_memory(suggestion_index)
    if not suggestion_data:
        print(f"Suggestion index {suggestion_index} not found in memory.")
        return

    embed = create_suggestion_embed(suggestion_data)

    try:
        message = await suggestion_channel.fetch_message(suggestion_message_id)
        guild = message.guild
        if not guild:
            print("Guild not found for suggestion message.")
            return

        view = discord.ui.View(timeout=None)

        # Add Upvote and Downvote buttons (visible to everyone)
        upvote_button = discord.ui.Button(label="Upvote", style=discord.ButtonStyle.success, custom_id=f"upvote_{suggestion_index}", emoji="✅")
        downvote_button = discord.ui.Button(label="Downvote", style=discord.ButtonStyle.danger, custom_id=f"downvote_{suggestion_index}", emoji="❌")

        async def upvote_callback(interaction: discord.Interaction):
            await handle_vote(interaction, suggestion_index, 'upvote')

        async def downvote_callback(interaction: discord.Interaction):
            await handle_vote(interaction, suggestion_index, 'downvote')

        upvote_button.callback = upvote_callback
        downvote_button.callback = downvote_callback

        view.add_item(upvote_button)
        view.add_item(downvote_button)

        # Add Approve, Reject, and Implement buttons (only interactable by Admins and Server Designers)
        if suggestion_data['status'] in ['Pending', 'Approved', 'Rejected', 'Implemented']:
            approve_button = discord.ui.Button(label="Approve", style=discord.ButtonStyle.green, custom_id=f"approve_{suggestion_index}", emoji="✔️")
            reject_button = discord.ui.Button(label="Reject", style=discord.ButtonStyle.red, custom_id=f"reject_{suggestion_index}", emoji="✖️")

            async def approve_callback(interaction: discord.Interaction):
                if not await can_manage_suggestion(interaction.user):
                    await interaction.response.send_message("You don't have permission to approve suggestions.", ephemeral=True)
                    return
                await handle_suggestion_action(interaction, suggestion_index, 'Approved')

            async def reject_callback(interaction: discord.Interaction):
                if not await can_manage_suggestion(interaction.user):
                    await interaction.response.send_message("You don't have permission to reject suggestions.", ephemeral=True)
                    return
                await handle_suggestion_action(interaction, suggestion_index, 'Rejected')

            approve_button.callback = approve_callback
            reject_button.callback = reject_callback

            view.add_item(approve_button)
            view.add_item(reject_button)

        if suggestion_data['status'] == 'Pending':
            implement_button = discord.ui.Button(label="Implement", style=discord.ButtonStyle.blurple, custom_id=f"implement_{suggestion_index}", emoji="⚙️")

            async def implement_callback(interaction: discord.Interaction):
                if not await can_manage_suggestion(interaction.user):
                    await interaction.response.send_message("You don't have permission to implement suggestions.", ephemeral=True)
                    return
                await implement_suggestion(interaction, suggestion_index)

            implement_button.callback = implement_callback
            view.add_item(implement_button)

        await message.edit(embed=embed, view=view)
    except discord.NotFound:
        print(f"Suggestion message {suggestion_message_id} not found in channel {SUGGESTION_CHANNEL_ID}.")
    except discord.Forbidden:
        print(f"Bot lacks permissions to edit message {suggestion_message_id} in channel {SUGGESTION_CHANNEL_ID}.")

async def handle_vote(interaction: discord.Interaction, suggestion_index: int, vote_type: str):
    await interaction.response.defer(ephemeral=True)

    suggestion_data = await get_suggestion_from_memory(suggestion_index)
    if not suggestion_data:
        await interaction.followup.send("Error: Suggestion not found.", ephemeral=True)
        return

    if suggestion_data.get('status') not in ['Pending', 'Approved', 'Rejected', 'Implemented']:
        await interaction.followup.send("This suggestion cannot be voted on.", ephemeral=True)
        return

    user_id_str = str(interaction.user.id)
    if user_id_str == str(suggestion_data.get('author').id):
        await interaction.followup.send("You cannot vote on your own suggestion!", ephemeral=True)
        return

    if VOTER_ROLE_IDS and not any(role.id in VOTER_ROLE_IDS for role in interaction.user.roles):
        await interaction.followup.send("You do not have the required role to vote on suggestions.", ephemeral=True)
        return

    upvotes = set(suggestion_data.get('upvotes', []))
    downvotes = set(suggestion_data.get('downvotes', []))
    changed = False

    if vote_type == 'upvote':
        if user_id_str in upvotes:
            upvotes.remove(user_id_str)
            await interaction.followup.send("Your upvote has been removed.", ephemeral=True)
        else:
            upvotes.add(user_id_str)
            if user_id_str in downvotes:
                downvotes.remove(user_id_str)
            await interaction.followup.send("You have upvoted this suggestion!", ephemeral=True)
        changed = True
    elif vote_type == 'downvote':
        if user_id_str in downvotes:
            downvotes.remove(user_id_str)
            await interaction.followup.send("Your downvote has been removed.", ephemeral=True)
        else:
            downvotes.add(user_id_str)
            if user_id_str in upvotes:
                upvotes.remove(user_id_str)
            await interaction.followup.send("You have downvoted this suggestion!", ephemeral=True)
        changed = True

    if changed:
        updated_data = {
            'upvotes': list(upvotes),
            'downvotes': list(downvotes)
        }
        await update_suggestion_in_memory(suggestion_index, updated_data)
        await update_suggestion_message(suggestion_index, suggestion_data['message_id'])

async def handle_suggestion_action(interaction: discord.Interaction, suggestion_index: int, new_status: str, reason: str = None):
    await interaction.response.defer(ephemeral=True)

    suggestion_data = await get_suggestion_from_memory(suggestion_index)
    if not suggestion_data:
        await interaction.followup.send("Error: Suggestion not found.", ephemeral=True)
        return

    if suggestion_data.get('status') == new_status:
        await interaction.followup.send(f"This suggestion is already **{new_status}**.", ephemeral=True)
        return

    updated_data = {
        'status': new_status
    }
    if new_status == 'Rejected' and reason:
        updated_data['rejection_reason'] = reason

    success = await update_suggestion_in_memory(suggestion_index, updated_data)

    if not success:
        await interaction.followup.send("Failed to update suggestion status.", ephemeral=True)
        return

    updated_suggestion_data = await get_suggestion_from_memory(suggestion_index)
    if not updated_suggestion_data:
        await interaction.followup.send("Error fetching updated suggestion data.", ephemeral=True)
        return

    message_id = updated_suggestion_data.get('message_id')
    if message_id:
        await update_suggestion_message(suggestion_index, message_id)
        await interaction.followup.send(f"Suggestion successfully marked as **{new_status}**.", ephemeral=True)

    author = updated_suggestion_data.get('author')
    if author:
        await notify_suggestion_author(author, new_status, updated_suggestion_data['suggestion_text'], reason)

    await log_suggestion_action(suggestion_index, interaction.user, new_status, reason)

async def handle_suggestion_action_by_message_id(ctx, message_id: int, new_status: str, reason: str = None):
    # Find the suggestion with the matching message ID
    suggestion_index = None
    for idx, data in suggestions.items():
        if data.get('message_id') == message_id:
            suggestion_index = idx
            break

    if suggestion_index is None:
        await ctx.send("**[Bot]** No suggestion found with that message ID.", delete_after=8)
        return None, None

    suggestion_data = await get_suggestion_from_memory(suggestion_index)
    if not suggestion_data:
        await ctx.send("**[Bot]** Error: Suggestion data not found.", delete_after=8)
        return None, None

    if suggestion_data.get('status') != 'Pending':
        await ctx.send("**[Bot]** This suggestion is no longer pending and cannot be modified.", delete_after=8)
        return None, None

    updated_data = {
        'status': new_status
    }
    if new_status == 'Rejected' and reason:
        updated_data['rejection_reason'] = reason

    success = await update_suggestion_in_memory(suggestion_index, updated_data)

    if not success:
        await ctx.send("**[Bot]** Failed to update suggestion status. Please try again.", delete_after=8)
        return None, None

    updated_suggestion_data = await get_suggestion_from_memory(suggestion_index)
    if not updated_suggestion_data:
        await ctx.send("**[Bot]** Error fetching updated suggestion data.", delete_after=8)
        return None, None

    message_id = updated_suggestion_data.get('message_id')
    if message_id:
        await update_suggestion_message(suggestion_index, message_id)

    return suggestion_index, updated_suggestion_data

# --- Special Function for Implementation (Ticket System) ---
async def implement_suggestion(interaction: discord.Interaction, suggestion_index: int):
    await interaction.response.defer(ephemeral=True)

    suggestion_data = await get_suggestion_from_memory(suggestion_index)
    if not suggestion_data:
        await interaction.followup.send("Error: Suggestion not found.", ephemeral=True)
        return

    if suggestion_data.get('status') != 'Pending':
        await interaction.followup.send("This suggestion is no longer pending and cannot be implemented.", ephemeral=True)
        return

    guild = interaction.guild
    if not guild:
        await interaction.followup.send("This action can only be performed in a server.", ephemeral=True)
        return

    author = suggestion_data.get('author')
    staff_roles = [guild.get_role(r_id) for r_id in STAFF_ROLE_IDS if guild.get_role(r_id)]

    # Set up permissions for the private channel
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    for role in staff_roles:
        if role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    if author:
        overwrites[author] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    # Create a private channel (not under a category)
    channel_name = f"suggestion-ticket-{suggestion_index}"
    try:
        discussion_channel = await guild.create_text_channel(
            channel_name,
            overwrites=overwrites,
            topic=f"Discussion for suggestion: {suggestion_data.get('suggestion_text')[:100]}..."
        )
        initial_message_content = (
            f"📋 **Suggestion Discussion Channel**\n"
            f"**Author:** {author.mention if author else suggestion_data.get('author_name')}\n"
            f"**Suggestion:** {suggestion_data.get('suggestion_text')}\n\n"
            f"**Participants:** {', '.join(r.mention for r in staff_roles if r)}\n"
            "Let's discuss the implementation details here!"
        )
        await discussion_channel.send(initial_message_content)
        
        if author:
            await discussion_channel.send(f"{author.mention}, your suggestion has been moved to discussion! Please join us here.")
        
        updated_data = {
            'status': 'Implemented',
            'discussion_channel_id': discussion_channel.id
        }
        await update_suggestion_in_memory(suggestion_index, updated_data)

        message_id = suggestion_data.get('message_id')
        if message_id:
            await update_suggestion_message(suggestion_index, message_id)
            await interaction.followup.send(f"Suggestion has been marked as **Implemented**. A private discussion channel has been created: {discussion_channel.mention}.", ephemeral=True)

        await notify_suggestion_author(author, 'Implemented', suggestion_data['suggestion_text'])
        await log_suggestion_action(suggestion_index, interaction.user, 'Implemented')

    except discord.Forbidden:
        await interaction.followup.send("Bot lacks permissions to create channels or set overwrites. Please check my role permissions (Manage Channels, Manage Roles).", ephemeral=True)
        return
    except Exception as e:
        await interaction.followup.send(f"An error occurred while creating the discussion channel: {e}", ephemeral=True)
        return

# --- Discord Bot Events ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    global user_statuses, suggestions, status_embed_message_id, suggestion_counter
    user_statuses.clear()
    suggestions.clear()
    status_embed_message_id = None
    suggestion_counter = 0

    await update_status_embed()
    print("Bot is ready. All data (statuses, suggestions) is stored in-memory and will be lost on bot restart.")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.mentions and bot.user not in message.mentions:
        for user_mentioned in message.mentions:
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
                    pass

    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        if ctx.message.content.startswith(STATUS_COMMAND_PREFIX) or \
           ctx.message.content.startswith(SUGGESTION_COMMAND_PREFIX) or \
           ctx.message.content.startswith(bot.user.mention):
            await ctx.send(f"**[Bot]** That command doesn't exist! Use `{STATUS_COMMAND_PREFIX}statushelp` or `{SUGGESTION_COMMAND_PREFIX}suggesthelp`.", delete_after=8)
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"**[Bot]** Missing argument. Please check the command syntax.", delete_after=8)
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"**[Bot]** Invalid argument. Please provide a valid message ID (a number).", delete_after=8)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"**[Bot]** Command on cooldown. Try again in {error.retry_after:.2f} seconds.", delete_after=8)
    elif isinstance(error, commands.MissingPermissions) or isinstance(error, commands.BotMissingPermissions):
        await ctx.send("**[Bot]** I don't have the necessary permissions for that, or you don't.", delete_after=8)
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("**[Bot]** This command cannot be used in private messages.", delete_after=8)
    else:
        await ctx.send(f"**[Bot]** An unexpected error occurred: `{error}`", delete_after=8)

# --- Status Commands ---
async def process_status_command(ctx, status_text, creative_response, target_user: discord.Member = None):
    try:
        await ctx.message.delete(delay=5)
    except discord.Forbidden:
        pass

    if target_user:
        if ctx.author.id == target_user.id:
            pass
        elif await is_staff(ctx.author):
            pass
        else:
            try:
                bot_response = await ctx.send(f"**[Bot]** {ctx.author.mention}, you do not have permission to set {target_user.display_name}'s status.", delete_after=8)
                await bot_response.delete(delay=8)
            except discord.Forbidden:
                pass
            return

        user_to_set_status_for = target_user
        response_mention = target_user.mention
        response_display_name = target_user.display_name
        final_creative_response = f"Status for {response_display_name} set to **{status_text}**! " + creative_response.replace(ctx.author.display_name, response_display_name)
    else:
        user_to_set_status_for = ctx.author
        response_mention = ctx.author.mention
        response_display_name = ctx.author.display_name
        final_creative_response = creative_response

    user_id_str = str(user_to_set_status_for.id)
    user_statuses[user_id_str] = {
        'status': status_text,
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    await set_all_user_statuses_in_memory(user_statuses)
    await update_status_embed()
    try:
        bot_response = await ctx.send(f"**[Bot]** {response_mention}, {final_creative_response}")
        await bot_response.delete(delay=8)
    except discord.Forbidden:
        pass

@bot.command(name='dl', aliases=['do_later'])
async def do_later(ctx, target: discord.Member = None):
    await process_status_command(ctx, "Do Later", "Task marked for later. Focus on now! 🚧", target)

@bot.command(name='s', aliases=['sleep'])
async def sleeping(ctx, target: discord.Member = None):
    await process_status_command(ctx, "Sleeping", "You're in dreamland. We'll keep it quiet. 😴", target)

@bot.command(name='f', aliases=['free'])
async def free(ctx, target: discord.Member = None):
    await process_status_command(ctx, "Free", "Ready for action! Let’s go! ✅", target)

@bot.command(name='srn', aliases=['studying'])
async def studying_right_now(ctx, target: discord.Member = None):
    await process_status_command(ctx, "Studying Right Now", "Deep in study mode! Keep it up! 📚", target)

@bot.command(name='o', aliases=['out'])
async def outside(ctx, target: discord.Member = None):
    await process_status_command(ctx, "Outside", "Enjoy the outdoors! We'll catch you later. 🚶‍♂️", target)

@bot.command(name='b', aliases=['break'])
async def on_break(ctx, target: discord.Member = None):
    await process_status_command(ctx, "On Break", "Time to recharge! See you soon. ☕", target)

@bot.command(name='clearstatus')
async def clear_status(ctx, target: discord.Member = None):
    try:
        await ctx.message.delete(delay=5)
    except discord.Forbidden:
        pass

    user_to_clear_status_for = target if target else ctx.author

    if user_to_clear_status_for.id != ctx.author.id and not await is_staff(ctx.author):
        try:
            bot_response = await ctx.send(f"**[Bot]** {ctx.author.mention}, you do not have permission to clear {user_to_clear_status_for.display_name}'s status.", delete_after=8)
            await bot_response.delete(delay=8)
        except discord.Forbidden:
            pass
        return

    user_id_str = str(user_to_clear_status_for.id)
    if user_id_str in user_statuses:
        del user_statuses[user_id_str]
        await set_all_user_statuses_in_memory(user_statuses)
        await update_status_embed()
        try:
            bot_response = await ctx.send(f"**[Bot]** {user_to_clear_status_for.mention}'s status has been cleared! 🤔")
            await bot_response.delete(delay=8)
        except discord.Forbidden:
            pass
    else:
        try:
            bot_response = await ctx.send(f"**[Bot]** No status to clear for {user_to_clear_status_for.display_name}! 🤔")
            await bot_response.delete(delay=8)
        except discord.Forbidden:
            pass

@bot.command(name='status')
async def show_status(ctx, target: discord.Member = None):
    try:
        await ctx.message.delete(delay=5)
    except discord.Forbidden:
        pass

    user_to_show_status_for = target if target else ctx.author
    user_id_str = str(user_to_show_status_for.id)
    
    response = ""
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
        except (ValueError, TypeError):
            display_time_discord = timestamp_str

        response = f"{user_to_show_status_for.display_name}'s status: **{status_text}** (Updated: {display_time_discord})"
    else:
        response = f"No status set for {user_to_show_status_for.display_name}. Use `{STATUS_COMMAND_PREFIX}f`, `{STATUS_COMMAND_PREFIX}s`, etc., to set one!"
    try:
        bot_response = await ctx.send(f"**[Bot]** {response}")
        await bot_response.delete(delay=8)
    except discord.Forbidden:
        pass

@bot.command(name='statushelp')
async def status_help(ctx):
    try:
        await ctx.message.delete(delay=5)
    except discord.Forbidden:
        pass
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
            f"`{STATUS_COMMAND_PREFIX}f [mention]` - Set status to 'Free'\n"
            f"`{STATUS_COMMAND_PREFIX}s [mention]` - Set status to 'Sleeping'\n"
            f"`{STATUS_COMMAND_PREFIX}dl [mention]` - Set status to 'Do Later'\n"
            f"`{STATUS_COMMAND_PREFIX}srn [mention]` - Set status to 'Studying Right Now'\n"
            f"`{STATUS_COMMAND_PREFIX}o [mention]` - Set status to 'Outside'\n"
            f"`{STATUS_COMMAND_PREFIX}b [mention]` - Set status to 'On Break'\n"
            f"`{STATUS_COMMAND_PREFIX}clearstatus [mention]` - Clear your/mentioned user's status\n"
            f"`{STATUS_COMMAND_PREFIX}status [mention]` - Show your/mentioned user's current status\n"
            f"`{STATUS_COMMAND_PREFIX}statushelp` - Show this help message"
        ),
        inline=False
    )
    help_embed.add_field(
        name="Setting Others' Status:",
        value=(
            "You can set another user's status by mentioning them after the command (e.g., `.f @User`).\n"
            "**Note:** Only staff members can set/clear statuses for other users. Non-staff can only manage their own status."
        ),
        inline=False
    )
    help_embed.set_footer(text="Note: All status data is in-memory and resets when the bot restarts.")
    await ctx.send(embed=help_embed)

# --- Suggestion System Commands ---
@bot.command(name='suggest')
async def submit_suggestion(ctx, *, suggestion: str):
    if not ctx.guild:
        await ctx.send("**[Bot]** Suggestions can only be submitted in a server channel.", delete_after=8)
        return

    if not suggestion:
        await ctx.send(f"**[Bot]** Please provide a suggestion! Usage: `{SUGGESTION_COMMAND_PREFIX}suggest <your suggestion>`", delete_after=8)
        return

    # Delete the user's command message after 4 seconds
    try:
        await ctx.message.delete(delay=4)
    except discord.Forbidden:
        pass

    # Post a temporary confirmation embed in the guide channel
    guide_channel = bot.get_channel(GUIDE_CHANNEL_ID)
    if guide_channel and ctx.channel.id == GUIDE_CHANNEL_ID:
        confirmation_embed = discord.Embed(
            title="✅ Suggestion Submitted",
            description=f"Your suggestion has been posted to the staff, they will review...\n\n"
                        f"**Suggestion:** {suggestion}",
            color=0x00FF00,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        confirmation_embed.set_footer(text="This message will auto-delete in 8 seconds.")
        try:
            bot_response = await guide_channel.send(embed=confirmation_embed)
            await bot_response.delete(delay=8)
        except discord.Forbidden:
            pass

    # Store the suggestion data
    suggestion_data = {
        'author': ctx.author,
        'suggestion_text': suggestion,
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status': 'Pending',
        'upvotes': [],
        'downvotes': [],
        'message_id': None
    }

    suggestion_index = await save_suggestion_in_memory(suggestion_data)

    # Post the suggestion embed in the main suggestion channel (permanent)
    suggestion_channel = bot.get_channel(SUGGESTION_CHANNEL_ID)
    if suggestion_channel:
        initial_embed = create_suggestion_embed(suggestion_data)

        view = discord.ui.View(timeout=None)
        upvote_button = discord.ui.Button(label="Upvote", style=discord.ButtonStyle.success, custom_id=f"upvote_{suggestion_index}", emoji="✅")
        downvote_button = discord.ui.Button(label="Downvote", style=discord.ButtonStyle.danger, custom_id=f"downvote_{suggestion_index}", emoji="❌")

        async def upvote_callback(interaction: discord.Interaction):
            await handle_vote(interaction, suggestion_index, 'upvote')

        async def downvote_callback(interaction: discord.Interaction):
            await handle_vote(interaction, suggestion_index, 'downvote')

        upvote_button.callback = upvote_callback
        downvote_button.callback = downvote_callback

        view.add_item(upvote_button)
        view.add_item(downvote_button)

        # Add management buttons (only interactable by Admins and Server Designers)
        approve_button = discord.ui.Button(label="Approve", style=discord.ButtonStyle.green, custom_id=f"approve_{suggestion_index}", emoji="✔️")
        reject_button = discord.ui.Button(label="Reject", style=discord.ButtonStyle.red, custom_id=f"reject_{suggestion_index}", emoji="✖️")
        implement_button = discord.ui.Button(label="Implement", style=discord.ButtonStyle.blurple, custom_id=f"implement_{suggestion_index}", emoji="⚙️")

        async def approve_callback(interaction: discord.Interaction):
            if not await can_manage_suggestion(interaction.user):
                await interaction.response.send_message("You don't have permission to approve suggestions.", ephemeral=True)
                return
            await handle_suggestion_action(interaction, suggestion_index, 'Approved')

        async def reject_callback(interaction: discord.Interaction):
            if not await can_manage_suggestion(interaction.user):
                await interaction.response.send_message("You don't have permission to reject suggestions.", ephemeral=True)
                return
            await handle_suggestion_action(interaction, suggestion_index, 'Rejected')

        async def implement_callback(interaction: discord.Interaction):
            if not await can_manage_suggestion(interaction.user):
                await interaction.response.send_message("You don't have permission to implement suggestions.", ephemeral=True)
                return
            await implement_suggestion(interaction, suggestion_index)

        approve_button.callback = approve_callback
        reject_button.callback = reject_callback
        implement_button.callback = implement_callback

        view.add_item(approve_button)
        view.add_item(reject_button)
        view.add_item(implement_button)

        try:
            suggestion_message = await suggestion_channel.send(embed=initial_embed, view=view)
            await update_suggestion_in_memory(suggestion_index, {'message_id': suggestion_message.id})
        except discord.Forbidden:
            print(f"Bot lacks permissions to send messages in suggestion channel {SUGGESTION_CHANNEL_ID}.")

    # Send a DM to the author
    try:
        dm_embed = discord.Embed(
            title="Suggestion Submitted",
            description="Your suggestion has been submitted successfully!",
            color=0x00FF00
        )
        dm_embed.add_field(name="Suggestion", value=suggestion, inline=False)
        dm_embed.set_footer(text="You will be notified of any updates!")
        await ctx.author.send(embed=dm_embed)
    except discord.Forbidden:
        pass

@bot.command(name='denied')
@commands.check(lambda ctx: any(role.id in STAFF_ROLE_IDS for role in ctx.author.roles))
async def deny_suggestion(ctx, message_id: int, *, reason: str):
    suggestion_index, updated_suggestion_data = await handle_suggestion_action_by_message_id(ctx, message_id, 'Rejected', reason)
    if suggestion_index is None or updated_suggestion_data is None:
        return

    author = updated_suggestion_data.get('author')
    if author:
        await notify_suggestion_author(author, 'Rejected', updated_suggestion_data['suggestion_text'], reason)

    await log_suggestion_action(suggestion_index, ctx.author, 'Rejected', reason)
    await ctx.send(f"**[Bot]** Suggestion with message ID {message_id} successfully marked as **Rejected** with reason: {reason}", delete_after=8)

@bot.command(name='approved')
@commands.check(lambda ctx: any(role.id in STAFF_ROLE_IDS for role in ctx.author.roles))
async def approve_suggestion(ctx, message_id: int):
    suggestion_index, updated_suggestion_data = await handle_suggestion_action_by_message_id(ctx, message_id, 'Approved')
    if suggestion_index is None or updated_suggestion_data is None:
        return

    author = updated_suggestion_data.get('author')
    if author:
        await notify_suggestion_author(author, 'Approved', updated_suggestion_data['suggestion_text'])

    await log_suggestion_action(suggestion_index, ctx.author, 'Approved')
    await ctx.send(f"**[Bot]** Suggestion with message ID {message_id} successfully marked as **Approved**.", delete_after=8)

@bot.command(name='suggesthelp')
async def suggest_help(ctx):
    help_embed = discord.Embed(
        title="💡 Suggestion System Help",
        description="Submit and manage suggestions with ease!",
        color=0x7289DA
    )
    help_embed.add_field(
        name="📝 Submit a Suggestion",
        value=f"Go to <#{GUIDE_CHANNEL_ID}> and use `{SUGGESTION_COMMAND_PREFIX}suggest <your suggestion>` to submit a suggestion.\n"
              f"**Example:** `{SUGGESTION_COMMAND_PREFIX}suggest Add a new game night event!`",
        inline=False
    )
    help_embed.add_field(
        name="🗳️ Voting & Management",
        value=f"Suggestions are posted in <#{SUGGESTION_CHANNEL_ID}>.\n"
              "• **Anyone** can vote using the ✅ Upvote and ❌ Downvote buttons.\n"
              "• **Admins and Server Designers** can manage suggestions using the Approve ✔️, Reject ✖️, or Implement ⚙️ buttons.",
        inline=False
    )
    staff_roles_mentions = ", ".join([f"<@&{r_id}>" for r_id in STAFF_ROLE_IDS if ctx.guild and ctx.guild.get_role(r_id)])
    if staff_roles_mentions:
        help_embed.add_field(
            name="👥 For Staff",
            value=f"Staff roles: {staff_roles_mentions}\n"
                  f"• Use `{SUGGESTION_COMMAND_PREFIX}approved <message_id>` to approve a suggestion.\n"
                  f"• Use `{SUGGESTION_COMMAND_PREFIX}denied <message_id> <reason>` to reject a suggestion with a reason.\n"
                  f"• When a suggestion is implemented, a private channel is created for discussion with the author.\n"
                  f"• To get the message ID, right-click the suggestion embed in <#{SUGGESTION_CHANNEL_ID}> and copy the ID.",
            inline=False
        )
    help_embed.set_footer(text="Suggestions are stored in-memory and reset on bot restart.")
    await ctx.send(embed=help_embed)

# --- Run Flask (Optional Web Server) ---
def run_flask():
    if not app.debug and not app.testing and not threading.current_thread().name == 'MainThread':
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "message": "Discord Bot is running!"})

# --- Main Bot Execution ---
async def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    try:
        discord_token = os.environ.get('DISCORD_BOT_TOKEN')
        if not discord_token:
            raise ValueError("DISCORD_BOT_TOKEN environment variable not set. Please check your .env file.")
        await bot.start(discord_token)
    except Exception as e:
        print(f"Error starting Discord bot: {e}")

if __name__ == '__main__':
    asyncio.run(main())
