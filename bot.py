import os
import logging
import socket
import asyncpg
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from dotenv import load_dotenv

# --- Logs ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# --- Variables de entorno ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.environ.get("PORT", 5000))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

if not BOT_TOKEN:
    raise RuntimeError("Falta BOT_TOKEN en variables de entorno")
if not DATABASE_URL:
    raise RuntimeError("Falta DATABASE_URL en variables de entorno")
if not RENDER_EXTERNAL_URL:
    raise RuntimeError("Falta RENDER_EXTERNAL_URL en variables de entorno")

# --- Conexión a Supabase con asyncpg (forzando IPv4) ---
async def get_connection():
    host = "db.zndejlffvlznbhsfozst.supabase.co"
    ipv4 = socket.gethostbyname(host)  # fuerza IPv4
    dsn = DATABASE_URL.replace(host, ipv4)
    return await asyncpg.connect(dsn)

# --- Teclados ---
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Balance", callback_data="menu_balance")],
        [InlineKeyboardButton("🔗 Subir seguimiento", callback_data="menu_seguimiento")],
        [InlineKeyboardButton("🎬 Subir video", callback_data="menu_video")],
    ])

def back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Menú principal", callback_data="menu_principal")]]
    )

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = await get_connection()
    await conn.execute("""
        INSERT INTO users (telegram_id) VALUES ($1)
        ON CONFLICT (telegram_id) DO NOTHING
    """, user_id)
    await conn.close()

    await update.message.reply_text(
        f"👋 Hola {update.effective_user.first_name}, bienvenido.\n"
        "Usa el menú o comandos como /balance.",
        reply_markup=main_menu_keyboard()
    )

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = await get_connection()
    row = await conn.fetchrow("SELECT balance FROM users WHERE telegram_id=$1", user_id)
    balance = row["balance"] if row else 0
    await conn.close()

    await update.message.reply_text(
        f"💰 Tu balance actual: {balance} puntos",
        reply_markup=back_to_menu_keyboard()
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ Usa el menú o comandos como /start y /balance.", reply_markup=main_menu_keyboard())

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_principal":
        await query.edit_message_text("🏠 Menú principal", reply_markup=main_menu_keyboard())

    elif data == "menu_balance":
        user_id = query.from_user.id
        conn = await get_connection()
        row = await conn.fetchrow("SELECT balance FROM users WHERE telegram_id=$1", user_id)
        balance = row["balance"] if row else 0
        await conn.close()
        await query.edit_message_text(f"💰 Tu balance actual: {balance} puntos", reply_markup=back_to_menu_keyboard())

    elif data == "menu_seguimiento":
        await query.edit_message_text("🔗 Envíame el link del perfil a seguir:", reply_markup=back_to_menu_keyboard())

    elif data == "menu_video":
        await query.edit_message_text("🎬 Envíame el link del video y breve descripción:", reply_markup=back_to_menu_keyboard())

# --- Flask + Telegram Webhook ---
app = Flask(__name__)
application = Application.builder().token(BOT_TOKEN).build()

# Registrar handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("balance", cmd_balance))
application.add_handler(CallbackQueryHandler(menu_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

# Endpoint para recibir updates de Telegram
@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "ok"

if __name__ == "__main__":
    print("Webhook URL:", f"{RENDER_EXTERNAL_URL}/webhook")  # Depuración
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=f"{RENDER_EXTERNAL_URL}/webhook",
    )