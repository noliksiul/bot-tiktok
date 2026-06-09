import os
import logging
import asyncpg
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# Configuración fija
TOKEN = "6564290496:AAFfyjhNUHMQaryJgMxK-gBNGkJX41Cay0A"
CHANNEL_APOYO_ID = -1001234567890
DATABASE_URL = "postgresql://base1_5t6z_user:91oGVipwRNCO95hKH1cJzqHL86Bt3rEN@dpg-d8k9r6ernols739dukjg-a.virginia-postgres.render.com/base1_5t6z?sslmode=require"

logging.basicConfig(level=logging.INFO)

# Flask para webhook
app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

# Inicializar tablas al arrancar


async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        tiktok_user TEXT UNIQUE NOT NULL,
        puntos NUMERIC DEFAULT 0,
        referido_id BIGINT REFERENCES users(id)
    );
    """)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(id),
        link TEXT NOT NULL,
        titulo TEXT,
        descripcion TEXT,
        fecha TIMESTAMP DEFAULT NOW()
    );
    """)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS interacciones (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(id),
        video_id BIGINT REFERENCES videos(id),
        tipo TEXT,
        estado TEXT DEFAULT 'pendiente',
        puntos NUMERIC DEFAULT 0,
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

# Conexión rápida


async def get_db():
    return await asyncpg.connect(DATABASE_URL)

# Menú principal


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📋 Registrar TikTok", callback_data="registro")],
        [InlineKeyboardButton("🎥 Subir Video", callback_data="subir_video")],
        [InlineKeyboardButton("💰 Ganar Monedas", callback_data="ganar")],
        [InlineKeyboardButton("👥 Referidos", callback_data="referidos")],
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

    elif query.data == "ganar":
        await query.edit_message_text("👉 Aquí se abriría la mini WebApp con contador.")

    elif query.data == "referidos":
        await query.edit_message_text(f"Tu código de referido es: {telegram_id}")

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

# Guardar usuario TikTok y videos


async def mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.message.from_user.id
    texto = update.message.text.strip()

    if context.user_data.get("esperando_tiktok"):
        conn = await get_db()
        try:
            await conn.execute("""
                INSERT INTO users (telegram_id, tiktok_user)
                VALUES ($1, $2)
                ON CONFLICT (telegram_id) DO NOTHING
            """, telegram_id, texto)
            await update.message.reply_text(f"✅ Registrado como {texto}")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Error: {e}")
        finally:
            await conn.close()
        context.user_data["esperando_tiktok"] = False

    elif context.user_data.get("esperando_video"):
        conn = await get_db()
        try:
            user = await conn.fetchrow("SELECT id FROM users WHERE telegram_id=$1", telegram_id)
            if user:
                await conn.execute("""
                    INSERT INTO videos (user_id, link)
                    VALUES ($1, $2)
                """, user["id"], texto)
                # Publicar en canal
                await application.bot.send_message(chat_id=CHANNEL_APOYO_ID, text=f"🎥 Nuevo video subido: {texto}")
                await update.message.reply_text("🎥 Video guardado y enviado al canal.")
                # Registrar movimiento
                await conn.execute("""
                    INSERT INTO movimientos (user_id, descripcion, puntos)
                    VALUES ($1, $2, $3)
                """, user["id"], "Subida de video", 0)
            else:
                await update.message.reply_text("⚠️ Primero regístrate con tu usuario de TikTok.")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Error: {e}")
        finally:
            await conn.close()
        context.user_data["esperando_video"] = False

# Handlers
application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND, mensaje))
application.add_handler(CallbackQueryHandler(button))


@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put_nowait(update)
    return "ok"


if __name__ == "__main__":
    import asyncio
    asyncio.run(init_db())  # crea tablas al iniciar
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        url_path=TOKEN,
        webhook_url=f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
    )
