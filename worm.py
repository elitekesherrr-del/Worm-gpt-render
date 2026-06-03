import os
import hashlib
import time
import requests
import logging
import threading
import json
import asyncio

from flask import Flask

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    BotCommand
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from telegram.error import TelegramError

# ─────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# BOT CONFIGURATION & ADMIN SECRETS
# ─────────────────────────────────────────
BOT_TOKEN = "8716586303:AAE1nuOa3xPNLcEF-TYaLFgwcBCOWlCrnC0"
SECRET_CODE = "FDJGSLGSGSFJS"  # Admin panel secret key

BOT_NAME = "Worm GPT AI"
BOT_OWNER = "Sir Kanha"
ADMIN_USERNAME = "@K4NHA_EMPIRE"

CHANNELS = [
    {
        "id": "@K4NHA_EMPIRE",
        "link": "https://t.me/K4NHA_EMPIRE"
    },
    {
        "id": "@K3NHA_EMPIRE",
        "link": "https://t.me/K3NHA_EMPIRE"
    }
]

# ─────────────────────────────────────────
# USER DATA PERSISTENCE (For Admin Panel)
# ─────────────────────────────────────────
USER_DATA_FILE = "users.json"

def load_users():
    try:
        with open(USER_DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_users(users):
    with open(USER_DATA_FILE, "w") as f:
        json.dump(users, f, indent=2)

users_db = load_users()

def add_user(user_id, username, first_name):
    uid = str(user_id)
    if uid not in users_db:
        users_db[uid] = {
            "username": username or "None",
            "first_name": first_name or "None",
            "last_seen": time.time()
        }
        save_users(users_db)
    else:
        users_db[uid]["last_seen"] = time.time()
        save_users(users_db)

# ─────────────────────────────────────────
# API SETTINGS
# ─────────────────────────────────────────
CHAT_API_URL = "https://chat.hackaigc.com/api/chat"
CHAT_SECRET = "hackagic20251231"
CHAT_FP_SECRET = "hackagic251122"
CHAT_MODEL = "uncensored"

# ─────────────────────────────────────────
# LIMITS & COOLDOWN
# ─────────────────────────────────────────
MAX_MESSAGE_LENGTH = 4000
FREE_CREDITS_PER_DAY = 2
QUESTION_COOLDOWN = 40  # seconds

_conversations = {}
_user_limits = {}
_last_message_time = {}

# ─────────────────────────────────────────
# FLASK WEB SERVER (Render Hosting)
# ─────────────────────────────────────────
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Worm GPT AI Bot is online and active!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host='0.0.0.0', port=port)

# ─────────────────────────────────────────
# CORE FUNCTIONS (SHA256, UID, TOKEN)
# ─────────────────────────────────────────
def sha256(text: str):
    return hashlib.sha256(text.encode()).hexdigest()

def make_guest_uid(user_id: int):
    dt = f"tg_{user_id}"
    t = len(dt) // 2
    raw = dt[t:] + CHAT_FP_SECRET + dt[:t]
    hashed = sha256(raw)
    return "guest_" + hashed[:32]

def make_request_token(user_id: str, timestamp: int):
    raw = f"{CHAT_SECRET}:{user_id}:{timestamp}"
    return sha256(raw)[:32]

# ─────────────────────────────────────────
# FORCE SUB CHECK
# ─────────────────────────────────────────
async def check_force_join(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    missing_channels = []
    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(chat_id=channel["id"], user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                missing_channels.append(channel)
        except TelegramError as e:
            logger.error(f"Join Check Error: {e}")
            missing_channels.append(channel)
    return missing_channels

def get_join_keyboard(missing_channels):
    keyboard = []
    for index, ch in enumerate(missing_channels, start=1):
        keyboard.append([InlineKeyboardButton(f"🔥 Join Empire {index}", url=ch["link"])])
    keyboard.append([InlineKeyboardButton("✅ Verify Access", callback_data="verify_join")])
    return InlineKeyboardMarkup(keyboard)

# ─────────────────────────────────────────
# MENU KEYBOARD
# ─────────────────────────────────────────
def reply_menu():
    keyboard = [
        ["🧠 Clear Memory"],
        ["👑 𝘼𝘿𝙈𝙄𝙉 𝙋𝘼𝙉𝙀𝙇 👑"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ─────────────────────────────────────────
# DAILY CREDIT & COOLDOWN LOGIC
# ─────────────────────────────────────────
def check_and_update_credits(user_id):
    current_time = time.time()
    one_day_ago = current_time - (24 * 3600)

    if user_id not in _user_limits:
        _user_limits[user_id] = []

    _user_limits[user_id] = [t for t in _user_limits[user_id] if t > one_day_ago]

    if len(_user_limits[user_id]) >= FREE_CREDITS_PER_DAY:
        oldest_request = _user_limits[user_id][0]
        remaining = int((oldest_request + (24 * 3600)) - current_time)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        return False, f"☠️ FREE LIMIT EXCEEDED ☠️\n\n🔥 Daily Free Credits: {FREE_CREDITS_PER_DAY}\n⏳ Next Credit In: {hours}h {minutes}m"

    _user_limits[user_id].append(current_time)
    return True, ""

def check_cooldown(user_id):
    current_time = time.time()
    last_used = _last_message_time.get(user_id)
    if last_used:
        remaining = QUESTION_COOLDOWN - (current_time - last_used)
        if remaining > 0:
            return False, int(remaining)
    _last_message_time[user_id] = current_time
    return True, 0

async def send_long_message(msg, original, text):
    if len(text) <= MAX_MESSAGE_LENGTH:
        await msg.edit_text(text)
        return
    first = text[:MAX_MESSAGE_LENGTH]
    await msg.edit_text(first)
    remaining = text[MAX_MESSAGE_LENGTH:]
    while remaining:
        chunk = remaining[:MAX_MESSAGE_LENGTH]
        await original.reply_text(chunk)
        remaining = remaining[MAX_MESSAGE_LENGTH:]

# ─────────────────────────────────────────
# AI CHAT LOGIC
# ─────────────────────────────────────────
def ai_chat(user_id: int, user_message: str):
    guest_uid = make_guest_uid(user_id)
    history = _conversations.setdefault(user_id, [])
    history.append({"role": "user", "content": user_message})

    timestamp = int(time.time() * 1000)
    token = make_request_token(guest_uid, timestamp)

    payload = {
        "model": CHAT_MODEL,
        "messages": history,
        "stream": False,
        "user_id": guest_uid,
        "user_level": "free",
        "deviceId": guest_uid,
        "enableWebSearch": False,
        "images": [],
        "prompt": "",
        "temperature": 0.7,
        "usedVoiceInput": False,
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10)",
        "Origin": "https://chat.hackaigc.com",
        "Referer": "https://chat.hackaigc.com/",
        "X-Request-Timestamp": str(timestamp),
        "X-Request-Token": token,
        "Authorization": f"Bearer anonymous_{guest_uid}",
    }

    response = requests.post(CHAT_API_URL, json=payload, headers=headers, timeout=60)
    response.raise_for_status()
    reply = response.text.strip()

    if reply:
        history.append({"role": "assistant", "content": reply})
        if len(history) > 40:
            _conversations[user_id] = history[-40:]
    return reply or "No response."

# ─────────────────────────────────────────
# ADMIN PANEL LOGIC
# ─────────────────────────────────────────
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 *Admin Panel*\n\nPlease enter the secret code to continue.", parse_mode="Markdown")
    context.user_data["awaiting_admin_code"] = True

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "admin_users":
        if not users_db:
            await query.edit_message_text("No users have used the bot yet.")
            return
        user_list = []
        for uid, info in users_db.items():
            uname = info.get("username", "None")
            fname = info.get("first_name", "None")
            user_list.append(f"👤 {fname} | 🆔 `{uid}` | 📛 @{uname}")
        msg = "📊 *Total Users:* " + str(len(users_db)) + "\n\n" + "\n".join(user_list)
        if len(msg) > 4000:
            parts = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
            for part in parts:
                await query.message.reply_text(part, parse_mode="Markdown")
            await query.delete_message()
        else:
            await query.edit_message_text(msg, parse_mode="Markdown")

    elif query.data == "admin_broadcast":
        await query.edit_message_text("📢 *Broadcast Mode*\n\nSend me any message (text, photo, video, etc.). It will be sent to ALL users.\n\nType /cancel to abort.", parse_mode="Markdown")
        context.user_data["broadcast_mode"] = True

    elif query.data == "admin_close":
        await query.edit_message_text("Admin panel closed.")
        context.user_data.pop("broadcast_mode", None)

# ─────────────────────────────────────────
# COMMANDS & VERIFICATION
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    
    missing = await check_force_join(context, user.id)
    if missing:
        text = "☠️ ACCESS DENIED ☠️\n\n🔥 Join All Empire Channels\nTo Unlock Worm GPT AI\n\n⚡ Security Verification Required"
        await update.message.reply_text(text=text, reply_markup=get_join_keyboard(missing))
        return

    welcome = (
        "☠️ WORM GPT AI ACTIVATED ☠️\n\n"
        "👑 Made By Sir Kanha\n\n"
        "🔥 Status: VERIFIED USER\n"
        f"🎁 Free Credits: {FREE_CREDITS_PER_DAY}/24h\n"
        f"⏳ Cooldown: {QUESTION_COOLDOWN} Seconds\n\n"
        "⚡ Commands:\n"
        "/new - Clear AI Memory\n\n"
        "💀 Send Your Question..."
    )
    await update.message.reply_text(welcome, reply_markup=reply_menu())

async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    
    missing = await check_force_join(context, user.id)
    if missing:
        await update.message.reply_text("☠️ Access Blocked.\nJoin Channels First.", reply_markup=get_join_keyboard(missing))
        return

    _conversations.pop(user.id, None)
    await update.message.reply_text("🧠 Worm Memory Cleared Successfully.")

async def verify_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    add_user(user_id, query.from_user.username, query.from_user.first_name)
    await query.answer()

    missing = await check_force_join(context, user_id)
    if missing:
        await query.answer(text="⚠️ Join All Channels First!", show_alert=True)
        try:
            await query.edit_message_reply_markup(reply_markup=get_join_keyboard(missing))
        except:
            pass
        return

    try:
        await query.message.delete()
    except:
        pass

    success_text = "✅ ACCESS GRANTED ✅\n\n☠️ Worm GPT AI Unlocked\n\n🔥 You May Now Ask Questions"
    await context.bot.send_message(chat_id=user_id, text=success_text, reply_markup=reply_menu())

# ─────────────────────────────────────────
# MASTER MESSAGE HANDLER
# ─────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(user_id, update.effective_user.username, update.effective_user.first_name)

    # 1. BROADCAST MODE
    if context.user_data.get("broadcast_mode"):
        if update.message.text == "/cancel":
            context.user_data.pop("broadcast_mode")
            await update.message.reply_text("Broadcast cancelled.")
            return

        if not users_db:
            await update.message.reply_text("No users to broadcast to.")
            context.user_data.pop("broadcast_mode")
            return

        total = len(users_db)
        success = 0
        fail = 0
        await update.message.reply_text(f"📡 Broadcasting to {total} users... Please wait.")

        for uid_str in users_db.keys():
            try:
                uid = int(uid_str)
                await context.bot.copy_message(chat_id=uid, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
                success += 1
            except:
                fail += 1
            await asyncio.sleep(0.05) 

        await update.message.reply_text(f"✅ Broadcast completed!\nSent: {success}\nFailed: {fail}")
        context.user_data.pop("broadcast_mode")
        return

    if not update.message.text:
        return

    user_text = update.message.text.strip()

    # 2. ADMIN CODE CHECK
    if context.user_data.get("awaiting_admin_code"):
        if user_text == SECRET_CODE:
            context.user_data["awaiting_admin_code"] = False
            keyboard = [
                [InlineKeyboardButton("📊 View Users", callback_data="admin_users")],
                [InlineKeyboardButton("📢 Broadcast Message", callback_data="admin_broadcast")],
                [InlineKeyboardButton("❌ Close Panel", callback_data="admin_close")]
            ]
            await update.message.reply_text("✅ Access Granted!\n\nChoose an option:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text("❌ Wrong code. Access denied.")
            context.user_data["awaiting_admin_code"] = False
        return

    # 3. MENU BUTTONS
    if user_text == "👑 𝘼𝘿𝙈𝙄𝙉 𝙋𝘼𝙉𝙀𝙇 👑":
        await admin_panel(update, context)
        return
        
    if user_text == "🧠 Clear Memory":
        await cmd_new(update, context)
        return

    # 4. FORCE SUB CHECK BEFORE AI CHAT
    missing = await check_force_join(context, user_id)
    if missing:
        await update.message.reply_text("☠️ ACCESS REVOKED ☠️\n\n🔥 You Left Required Channels.\nJoin Again To Continue.", reply_markup=get_join_keyboard(missing))
        return

    # 5. COOLDOWN CHECK
    cooldown_ok, remaining = check_cooldown(user_id)
    if not cooldown_ok:
        await update.message.reply_text(f"⏳ Cooldown Active\n\n🔥 Wait {remaining} Seconds Before Asking Another Question.")
        return

    # 6. DAILY LIMIT CHECK
    allowed, error_msg = check_and_update_credits(user_id)
    if not allowed:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium Access", url=f"https://t.me/{ADMIN_USERNAME.replace('@', '')}")]])
        await update.message.reply_text(error_msg, reply_markup=keyboard)
        return

    # 7. AI CHAT EXECUTION
    thinking = await update.message.reply_text("☠️ Worm GPT Thinking...")
    try:
        reply = ai_chat(user_id, user_text)
        final_reply = f"☠️ WORM GPT AI ☠️\n\n{reply}\n\n👑 Made By Sir Kanha"
        await send_long_message(thinking, update.message, final_reply)
    except requests.exceptions.HTTPError as e:
        logger.error(e)
        await thinking.edit_text(f"❌ API ERROR: {e.response.status_code}")
        if _user_limits.get(user_id):
            _user_limits[user_id].pop()
    except Exception as e:
        logger.error(e)
        await thinking.edit_text("❌ SYSTEM FAILURE")
        if _user_limits.get(user_id):
            _user_limits[user_id].pop()

async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Restart the bot 💖"),
        BotCommand("new", "Clear AI Memory 🧠")
    ])

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    print("☠️ Worm GPT AI Starting...")
    
    # Threading for Render web service to prevent sleeping
    threading.Thread(target=run_web, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CallbackQueryHandler(verify_join, pattern="^verify_join$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    
    # Master message handler to handle Broadcasts, Admin panel, and AI chat without overlap
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    app.post_init = set_commands
    print("✅ Worm GPT AI Online!")
    app.run_polling(drop_pending_updates=True)

# ─────────────────────────────────────────
# RUN
# ─────────────────────────────────────────
if __name__ == "__main__":
    main()
  
