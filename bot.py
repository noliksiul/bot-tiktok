import os
import logging
import asyncpg
import asyncio
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, ContextTypes, CallbackQueryHandler, MessageHandler, CommandHandler, filters

# 🔑 Configuración
TOKEN = "6564290496:AAFfyjhNUHMQaryJgMxK-gBNGkJX41Cay0A"
CHANNEL_APOYO_ID = -1003468913370

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://bot_db_928z_user:JKnN8ksdWPLL2SjFjdJYJpbStVObMQY1@dpg-d9060b9o3t8c73bv09ig-a.oregon-postgres.render.com/bot_db_928z?sslmode=require"
)

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

# Crear tablas


async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        tiktok_user TEXT UNIQUE NOT NULL,
        puntos NUMERIC DEFAULT 0
    );""")
    await conn.execute("""CREATE TABLE IF NOT EXISTS videos (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(id),
        link TEXT NOT NULL,
        fecha TIMESTAMP DEFAULT NOW()
    );""")
    await conn.execute("""CREATE TABLE IF NOT EXISTS movimientos (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(id),
        descripcion TEXT,
        puntos NUMERIC,
        fecha TIMESTAMP DEFAULT NOW()
    );""")
    await conn.close()
    print("✅ Base inicializada correctamente")

# Handlers


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📋 Registrar TikTok", callback_data="registro")],
        [InlineKeyboardButton("🎥 Subir Video", callback_data="subir_video")],
        [InlineKeyboardButton("💰 Ganar Monedas", web_app=WebAppInfo(
            "https://bot-tiktok-8d3y.onrender.com/?id="+str(update.effective_user.id)))],
        [InlineKeyboardButton("💳 Saldo", callback_data="saldo")],
        [InlineKeyboardButton("📜 Últimos 5 Movimientos",
                              callback_data="movimientos")]
    ]
    await update.message.reply_text("Menú principal:", reply_markup=InlineKeyboardMarkup(keyboard))


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⚙️ Acción recibida")


async def mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Mensaje recibido")

application.add_handler(CommandHandler("start", menu))
application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND, mensaje))
application.add_handler(CallbackQueryHandler(button))

# Flask endpoint miniapp


@app.route("/")
def index():
    telegram_id = request.args.get("id")
    return f"<h1>Bienvenido usuario {telegram_id}</h1><p>Miniapp funcionando ✅</p>"

# Flask endpoint webhook


@app.route(f"/{TOKEN}", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    await application.process_update(update)
    return "OK"

# Main
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    # Configurar webhook en Telegram
    loop.run_until_complete(
        application.bot.set_webhook(
            "https://bot-tiktok-8d3y.onrender.com/" + TOKEN)
    )
    # Inicializar y arrancar dispatcher
    loop.run_until_complete(application.initialize())
    loop.run_until_complete(application.start())
    # Correr Flask
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
