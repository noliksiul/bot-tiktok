import os
import logging
import asyncpg
import asyncio
from flask import Flask, request, send_from_directory
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, ContextTypes, CallbackQueryHandler, MessageHandler, CommandHandler, filters

# 🔑 Configuración
TOKEN = os.getenv("TOKEN")  # en Render la variable se llama BOT_TOKEN
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN:
    raise ValueError("❌ No se encontró BOT_TOKEN en Render")

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

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

# Handlers


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
    elif update.callback_query:
        await update.callback_query.message.reply_text("Menú principal:", reply_markup=InlineKeyboardMarkup(keyboard))


async def registrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("✍️ Escribe tu usuario de TikTok:")


async def guardar_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        INSERT INTO users (telegram_id, tiktok_user, puntos)
        VALUES ($1, $2, 0)
        ON CONFLICT (telegram_id) DO UPDATE SET tiktok_user=$2
    """, update.effective_user.id, tiktok_user)
    await conn.close()
    await update.message.reply_text(f"✅ Usuario TikTok registrado: {tiktok_user}")

# Recibir datos de la miniapp


async def recibir_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.web_app_data and update.message.web_app_data.data == "continuar":
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("UPDATE users SET puntos = puntos + 2 WHERE telegram_id=$1", update.effective_user.id)
        await conn.execute("""
            INSERT INTO movimientos (user_id, descripcion, puntos)
            VALUES ((SELECT id FROM users WHERE telegram_id=$1), 'Video visto', 2)
        """, update.effective_user.id)
        await conn.close()
        await update.message.reply_text("🎉 Ganaste 2 puntos. Regresando al menú principal...")
        await menu(update, context)


async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = await asyncpg.connect(DATABASE_URL)
    puntos = await conn.fetchval("SELECT puntos FROM users WHERE telegram_id=$1", query.from_user.id)
    await conn.close()
    await query.message.reply_text(f"💳 Tu saldo actual: {puntos} puntos")


async def movimientos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("""
        SELECT descripcion, puntos, fecha
        FROM movimientos
        WHERE user_id=(SELECT id FROM users WHERE telegram_id=$1)
        ORDER BY fecha DESC LIMIT 5
    """, query.from_user.id)
    await conn.close()
    texto = "📜 Últimos movimientos:\n"
    for r in rows:
        texto += f"- {r['descripcion']} (+{r['puntos']} puntos)\n"
    await query.message.reply_text(texto)

# Dispatcher
application.add_handler(CommandHandler("start", menu))
application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND, guardar_usuario))
application.add_handler(CallbackQueryHandler(registrar, pattern="registro"))
application.add_handler(CallbackQueryHandler(saldo, pattern="saldo"))
application.add_handler(CallbackQueryHandler(
    movimientos, pattern="movimientos"))
application.add_handler(MessageHandler(
    filters.StatusUpdate.WEB_APP_DATA, recibir_webapp))

# Flask endpoints


@app.route("/index.html")
def serve_index():
    return send_from_directory("webapp", "index.html")


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
