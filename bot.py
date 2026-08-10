import os
import logging
import asyncpg
import asyncio
import threading
from flask import Flask, request, send_from_directory
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, ContextTypes, CallbackQueryHandler, MessageHandler, CommandHandler, filters

TOKEN = "6564290496:AAFfyjhNUHMQaryJgMxK-gBNGkJX41Cay0A"
DATABASE_URL = "postgresql://bot_db1_user:B2y3STMCDTW1HB7adfk2TBYzB10GyaAL@dpg-d9sfnlu7bikc739fl5gg-a.oregon-postgres.render.com/bot_db1?sslmode=require"

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

bot_loop = None  # loop global

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

application.add_handler(CommandHandler("start", menu))
# … tus otros handlers …

# Flask endpoints


@app.route("/index.html")
def serve_index():
    return send_from_directory("webapp", "index.html")


@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    if bot_loop:
        bot_loop.call_soon_threadsafe(
            asyncio.create_task, application.process_update(update))
    return "OK"

# Inicialización del bot en un hilo separado


def start_bot():
    global bot_loop
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)

    async def init():
        await application.initialize()
        await application.start()
        await application.bot.set_webhook(
            f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
        )

    bot_loop.run_until_complete(init())
    bot_loop.run_forever()


threading.Thread(target=start_bot, daemon=True).start()
