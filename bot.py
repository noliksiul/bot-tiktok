import os
import logging
import asyncpg
import asyncio
import threading
from flask import Flask, request, render_template_string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, ContextTypes, CallbackQueryHandler, MessageHandler, CommandHandler, filters

# 🔑 Credenciales
TOKEN = "6564290496:AAFfyjhNUHMQaryJgMxK-gBNGkJX41Cay0A"
CHANNEL_APOYO_ID = -1003468913370
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

# Crear tablas con columna id


async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        tiktok_user TEXT UNIQUE NOT NULL,
        puntos NUMERIC DEFAULT 0
    );
    """)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(id),
        link TEXT NOT NULL,
        fecha TIMESTAMP DEFAULT NOW()
    );
    """)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS movimientos (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(id),
        descripcion TEXT,
        puntos NUMERIC,
        fecha TIMESTAMP DEFAULT NOW()
    );
    """)
    await conn.close()


async def get_db():
    return await asyncpg.connect(DATABASE_URL)

# Menú principal


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

# Botones


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id

    if query.data == "registro":
        await query.edit_message_text("Envíame tu usuario de TikTok (sin @):")
        context.user_data["esperando_tiktok"] = True

    elif query.data == "subir_video":
        await query.edit_message_text("Envíame el link del video de TikTok:")
        context.user_data["esperando_video"] = True

    elif query.data == "saldo":
        conn = await get_db()
        user = await conn.fetchrow("SELECT puntos FROM users WHERE telegram_id=$1", telegram_id)
        if user:
            await query.edit_message_text(f"💳 Tu saldo actual es: {user['puntos']} monedas")
        else:
            await query.edit_message_text("⚠️ No estás registrado.")
        await conn.close()

    elif query.data == "movimientos":
        conn = await get_db()
        user = await conn.fetchrow("SELECT id FROM users WHERE telegram_id=$1", telegram_id)
        if user:
            rows = await conn.fetch("""
                SELECT descripcion, puntos, fecha
                FROM movimientos
                WHERE user_id=$1
                ORDER BY fecha DESC
                LIMIT 5
            """, user["id"])
            if rows:
                texto = "📜 Últimos 5 movimientos:\n"
                for r in rows:
                    texto += f"- {r['fecha'].strftime('%d/%m %H:%M')} | {r['descripcion']} | {r['puntos']} pts\n"
                await query.edit_message_text(texto)
            else:
                await query.edit_message_text("No tienes movimientos registrados.")
        else:
            await query.edit_message_text("⚠️ No estás registrado.")
        await conn.close()

# Mensajes


async def mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.message.from_user.id
    texto = update.message.text.strip()

    if context.user_data.get("esperando_tiktok"):
        conn = await get_db()
        await conn.execute("""
            INSERT INTO users (telegram_id, tiktok_user)
            VALUES ($1, $2)
            ON CONFLICT (telegram_id) DO NOTHING
        """, telegram_id, texto)
        await update.message.reply_text(f"✅ Registrado como {texto}")
        await conn.close()
        context.user_data["esperando_tiktok"] = False

    elif context.user_data.get("esperando_video"):
        conn = await get_db()
        user = await conn.fetchrow("SELECT id FROM users WHERE telegram_id=$1", telegram_id)
        if user:
            await conn.execute("INSERT INTO videos (user_id, link) VALUES ($1, $2)", user["id"], texto)
            try:
                await application.bot.send_message(chat_id=CHANNEL_APOYO_ID, text=f"🎥 Nuevo video subido: {texto}")
                await update.message.reply_text("✅ Tu video se guardó y se envió al canal.")
            except Exception as e:
                await update.message.reply_text(f"⚠️ Error al enviar al canal: {e}")
            await conn.execute("INSERT INTO movimientos (user_id, descripcion, puntos) VALUES ($1, $2, $3)", user["id"], "Subida de video", 0)
        else:
            await update.message.reply_text("⚠️ Primero regístrate con tu usuario de TikTok.")
        await conn.close()
        context.user_data["esperando_video"] = False

# Handlers
application.add_handler(CommandHandler("start", menu))
application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND, mensaje))
application.add_handler(CallbackQueryHandler(button))

# Flask endpoint para WebApp "Ganar Monedas"


@app.route("/")
def index():
    telegram_id = request.args.get("id")

    async def fetch_videos():
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("SELECT link FROM videos ORDER BY fecha DESC LIMIT 5")
        await conn.close()
        return rows

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    videos = loop.run_until_complete(fetch_videos())

    if not videos:
        return f"<h1>Bienvenido usuario {telegram_id}</h1><p>No hay videos disponibles para ti.</p>"

    html = f"<h1>Bienvenido usuario {telegram_id}</h1><h2>Últimos videos subidos:</h2><ul>"
    for v in videos:
        html += f"<li><a href='{v['link']}' target='_blank'>{v['link']}</a></li>"
    html += "</ul>"
    return render_template_string(html)

# Arrancar bot en hilo separado


def run_bot():
    asyncio.run(init_db())
    application.run_webhook(
        listen="0.0.0.0",
        port=8443,  # puerto interno para webhook
        url_path=TOKEN,
        webhook_url=f"https://bot-tiktok-8d3y.onrender.com/{TOKEN}"
    )


if __name__ == "__main__":
    # Hilo para el bot
    threading.Thread(target=run_bot, daemon=True).start()
    # Flask como servidor principal
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
