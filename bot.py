import asyncio
import sqlite3
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ChatAction
from dotenv import load_dotenv
import os

# ---------------- Load Bot Token ----------------
load_dotenv()
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise Exception("TOKEN not found in .env file")

# ---------------- Chat Tracking ----------------
active_chats = {}
waiting_users = []

# ---------------- SQLite ----------------
conn = sqlite3.connect("chatbot.db")
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    is_active INTEGER
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER,
    sender_username TEXT,
    receiver_id INTEGER,
    text TEXT,
    type TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

conn.commit()

# ---------------- Bottom Keyboard ----------------
end_chat_keyboard = ReplyKeyboardMarkup(
    [["🔚 End Chat"]],
    resize_keyboard=True,
    one_time_keyboard=False
)

# ---------------- Inline Buttons ----------------
restart_button = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔄 Start New Chat", callback_data="restart_chat")]
])


def register_user(user):
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, username, first_name, is_active) VALUES (?, ?, ?, ?)",
        (user.id, user.username, user.first_name, 1)
    )
    conn.commit()


def log_message(sender_id, sender_username, receiver_id, text, msg_type="text"):
    cursor.execute(
        "INSERT INTO messages (sender_id, sender_username, receiver_id, text, type) VALUES (?, ?, ?, ?, ?)",
        (sender_id, sender_username, receiver_id, text, msg_type)
    )
    conn.commit()


# ---------------- Commands ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        register_user(update.effective_user)

    await update.message.reply_text(
        "👋 Welcome! Start chatting with a stranger now:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Start Chatting", callback_data="start_chat")],
            [InlineKeyboardButton("📊 Active Users", callback_data="active_users")],
            [InlineKeyboardButton("❓ Help", callback_data="help_menu")]
        ])
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text(
        "❓ Help Menu\n\n"
        "• Start Chatting — find a random stranger\n"
        "• 🔚 End Chat — stop your current chat\n"
        "• Active Users — see active users",
        parse_mode="Markdown"
    )


async def active_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users_in_chats = len(active_chats) // 2
    waiting_count = len(waiting_users)
    total_active = (users_in_chats * 2) + waiting_count

    refresh_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="active_users")]
    ])

    msg = update.callback_query if update.callback_query else update.message

    await msg.edit_message_text(
        f"🌐 *Active Users*: {total_active}\n"
        f"💬 Chatting: {users_in_chats}\n"
        f"⏳ Waiting: {waiting_count}",
        parse_mode="Markdown",
        reply_markup=refresh_button
    )


# ---------------- Chat Matching ----------------
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None):
    if user_id is None:
        user_id = update.effective_user.id

    if update.effective_user:
        register_user(update.effective_user)

    if user_id in active_chats:
        await context.bot.send_message(
            chat_id=user_id,
            text="⚠️ You are already in a chat.",
            reply_markup=end_chat_keyboard
        )
        return

    if user_id in waiting_users:
        await context.bot.send_message(chat_id=user_id, text="⏳ You are already waiting…")
        return

    if waiting_users:
        partner_id = waiting_users.pop(0)

        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id

        await context.bot.send_message(
            chat_id=user_id,
            text="🎉 Connected! Say hi 👋",
            reply_markup=end_chat_keyboard
        )
        await context.bot.send_message(
            chat_id=partner_id,
            text="🎉 Connected! Say hi 👋",
            reply_markup=end_chat_keyboard
        )
    else:
        waiting_users.append(user_id)
        await context.bot.send_message(chat_id=user_id, text="🔍 Searching for a stranger…")


# ---------------- End Chat ----------------
async def end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in active_chats:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ You are not in a chat.",
            reply_markup=restart_button
        )
        return

    partner_id = active_chats[user_id]

    # Notify both and remove keyboard
    await context.bot.send_message(
        chat_id=partner_id,
        text="⚠️ The other user ended the chat.",
        reply_markup=ReplyKeyboardRemove()
    )
    await context.bot.send_message(
        chat_id=user_id,
        text="✅ Chat ended.",
        reply_markup=ReplyKeyboardRemove()
    )

    del active_chats[user_id]
    del active_chats[partner_id]


# ---------------- Forwarding ----------------
async def forward_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # If user pressed the "End Chat" button
    if text == "🔚 End Chat":
        await end(update, context)
        return

    if user_id not in active_chats:
        await update.message.reply_text("❌ You are not in a chat.")
        return

    partner_id = active_chats[user_id]

    await context.bot.send_chat_action(chat_id=partner_id, action=ChatAction.TYPING)
    await asyncio.sleep(0.5)

    await context.bot.send_message(chat_id=partner_id, text=text)
    log_message(user_id, update.effective_user.username, partner_id, text)


async def forward_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in active_chats:
        await update.message.reply_text("❌ You are not in a chat.")
        return

    partner_id = active_chats[user_id]
    caption = update.message.caption or ""

    await context.bot.send_chat_action(chat_id=partner_id, action=ChatAction.UPLOAD_PHOTO)
    await asyncio.sleep(0.5)

    await context.bot.send_photo(
        chat_id=partner_id,
        photo=update.message.photo[-1].file_id,
        caption=caption
    )

    log_message(user_id, update.effective_user.username, partner_id, caption, "photo")


# ---------------- Callback Handler ----------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "start_chat":
        await chat(update, context, user_id)

    elif query.data == "end_chat":
        await end(update, context)

    elif query.data == "restart_chat":
        if user_id in active_chats:
            partner = active_chats.pop(user_id)
            active_chats.pop(partner, None)

            await context.bot.send_message(
                chat_id=partner,
                text="⚠️ The other user left the chat.",
                reply_markup=ReplyKeyboardRemove()
            )

        if user_id in waiting_users:
            waiting_users.remove(user_id)

        await context.bot.send_message(
            chat_id=user_id,
            text="🔄 Starting a new chat search…",
            reply_markup=ReplyKeyboardRemove()
        )

        await chat(update, context, user_id)

    elif query.data == "active_users":
        await active_users(update, context)

    elif query.data == "help_menu":
        await help_command(update, context)


# ---------------- MAIN ----------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_text))
    app.add_handler(MessageHandler(filters.PHOTO, forward_photo))

    print("🚀 Bot is running…")
    app.run_polling()
