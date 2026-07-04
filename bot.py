import os
import logging
import asyncpg
import asyncio
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, ContextTypes, CallbackQueryHandler, MessageHandler, CommandHandler, filters

# 🔑 Configuración
TOKEN = os.getenv("TOKEN", "6564290496:AAFfyjhNUHMQaryJgMxK-gBNGkJX41Cay0A")
CHANNEL_APOYO_ID = -1003468913370
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

# Crear tablas


async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        tiktok_user TEXT UNIQUE,
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
            f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/?id="+str(update.effective_user.id)))],
        [InlineKeyboardButton("💳 Saldo", callback_data="saldo")],
        [InlineKeyboardButton("📜 Últimos 5 Movimientos",
                              callback_data="movimientos")]
    ]
    await update.message.reply_text("Menú principal:", reply_markup=InlineKeyboardMarkup(keyboard))


async def subir_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Guardar video de ejemplo en BD
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("INSERT INTO videos (user_id, link) VALUES ($1, $2)",
                       update.effective_user.id, "https://example.com/video.mp4")
    await conn.close()

    # Enviar mensaje inicial
    msg = await update.callback_query.message.reply_text("🎥 Video de ejemplo, espera 20 segundos...")

    # Esperar 20 segundos
    await asyncio.sleep(20)

    # Mostrar botón "Visto"
    keyboard = [[InlineKeyboardButton("✅ Visto", callback_data="visto")]]
    await msg.edit_text("🎥 Video terminado, marca como visto:", reply_markup=InlineKeyboardMarkup(keyboard))


async def visto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Sumar 2 puntos al usuario
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("UPDATE users SET puntos = puntos + 2 WHERE telegram_id = $1", query.from_user.id)
    await conn.execute("""
        INSERT INTO movimientos (user_id, descripcion, puntos)
        VALUES ((SELECT id FROM users WHERE telegram_id=$1), 'Video visto', 2)
    """, query.from_user.id)
    await conn.close()

    await query.edit_message_text("✅ Has ganado 2 puntos por ver el video")


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "subir_video":
        await subir_video(update, context)
    else:
        await query.answer()
        await query.edit_message_text("⚙️ Acción recibida")


async def mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Mensaje recibido")

# Registro de handlers
application.add_handler(CommandHandler("start", menu))
application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND, mensaje))
application.add_handler(CallbackQueryHandler(button))
application.add_handler(CallbackQueryHandler(visto, pattern="visto"))

# Flask endpoint miniapp


@app.route("/")
def index():
    telegram_id = request.args.get("id")
    return f"<h1>Bienvenido usuario {telegram_id}</h1><p>Miniapp funcionando ✅</p>"

# Flask endpoint webhook (síncrono)


@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    asyncio.run(application.process_update(update))
    return "OK"


# Main
if __name__ == "__main__":
    async def main():
        await init_db()
        await application.initialize()
        await application.start()
        await application.bot.set_webhook(
            f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
        )
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

    asyncio.run(main())
