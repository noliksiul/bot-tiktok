import os
import logging
import psycopg2
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
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")  # Render la provee automáticamente en producción

if not BOT_TOKEN:
    raise RuntimeError("Falta BOT_TOKEN en variables de entorno")
if not DATABASE_URL:
    raise RuntimeError("Falta DATABASE_URL en variables de entorno")

# --- Conexión a Supabase/Postgres ---
def get_connection():
    return psycopg2.connect(DATABASE_URL)

# --- Utils ---
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
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (telegram_id) VALUES (%s)
        ON CONFLICT (telegram_id) DO NOTHING
    """, (user_id,))
    conn.commit()
    cur.close(); conn.close()

    await update.message.reply_text(
        f"👋 Hola {update.effective_user.first_name}, bienvenido.\n"
        "Usa el menú o comandos como /balance.",
        reply_markup=main_menu_keyboard()
    )

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE telegram_id=%s", (user_id,))
    row = cur.fetchone()
    balance = row[0] if row else 0
    cur.close(); conn.close()

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
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT balance FROM users WHERE telegram_id=%s", (user_id,))
        row = cur.fetchone()
        balance = row[0] if row else 0
        cur.close(); conn.close()
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

# Endpoint que recibe las updates de Telegram
@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "ok"

if __name__ == "__main__":
    if not RENDER_EXTERNAL_URL:
        print("⚠️ RENDER_EXTERNAL_URL no está definida. En Render se define automáticamente.")
    # Inicia servidor webhook (abre puerto HTTP) y registra webhook en Telegram
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=f"https://{RENDER_EXTERNAL_URL}/webhook" if RENDER_EXTERNAL_URL else None
    )