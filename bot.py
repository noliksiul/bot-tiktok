import os
import logging
import asyncpg
import asyncio
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, ContextTypes, CommandHandler

TOKEN = "6564290496:AAFfyjhNUHMQaryJgMxK-gBNGkJX41Cay0A"
DATABASE_URL = "postgresql://bot_db1_user:B2y3STMCDTW1HB7adfk2TBYzB10GyaAL@dpg-d9sfnlu7bikc739fl5gg-a.oregon-postgres.render.com/bot_db1?sslmode=require"

logging.basicConfig(level=logging.INFO)

# Flask app para Gunicorn
app = Flask(__name__)


@app.route("/")
def index():
    return "Bot Telegram activo ✅"

# Crear tablas


async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        tiktok_user TEXT,
        puntos NUMERIC DEFAULT 0
    );""")
    await conn.execute("""CREATE TABLE IF NOT EXISTS movimientos (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(id),
        descripcion TEXT,
        puntos NUMERIC,
        fecha TIMESTAMP DEFAULT NOW()
    );""")
    await conn.close()

# Handler /start


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📋 Registrar TikTok", callback_data="registro")],
        [InlineKeyboardButton("🎥 Video de ejemplo",
                              web_app=WebAppInfo(f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/index.html"))],
        [InlineKeyboardButton("💳 Saldo", callback_data="saldo")],
        [InlineKeyboardButton("📜 Últimos 5 Movimientos",
                              callback_data="movimientos")]
    ]
    if update.message:
        await update.message.reply_text("Menú principal:", reply_markup=InlineKeyboardMarkup(keyboard))

# Bot
application = Application.builder().token(TOKEN).build()
application.add_handler(CommandHandler("start", menu))

# Inicialización del bot con polling


async def main():
    await init_db()
    await application.initialize()
    await application.start()
    await application.run_polling()   # <-- solo polling, sin webhook

# Arrancar el bot en un hilo separado para no bloquear Flask


def run_bot():
    asyncio.run(main())


threading.Thread(target=run_bot, daemon=True).start()
