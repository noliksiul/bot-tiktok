import os
import asyncio
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, ContextTypes, filters
import aiohttp
from bs4 import BeautifulSoup

# ⚠️ Token de tu bot COMUNIDAD Wuampira
BOT_TOKEN = "6564290496:AAFfyjhNUHMQaryJgMxK-gBNGkJX41Cay0A"

# ⚠️ ID de tu canal principal (reemplázalo con el real)
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001234567890"))

# ⚠️ URL pública de Render (ejemplo: https://comunidadcw.onrender.com)
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

app_flask = Flask(__name__)

# --- Estrategia 1: Solo texto ---


async def publish_text(context: ContextTypes.DEFAULT_TYPE, link: str):
    await context.bot.send_message(chat_id=CHANNEL_ID, text=f"🔗 Link directo:\n{link}")

# --- Estrategia 2: Mensaje con botón ---


async def publish_with_button(context: ContextTypes.DEFAULT_TYPE, link: str):
    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text="🌐 Ver video en TikTok",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Abrir TikTok", url=link)]])
    )

# --- Estrategia 3: Scraping de miniatura ---


async def fetch_tiktok_thumbnail(url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")
                og_image = soup.find("meta", property="og:image")
                if og_image and og_image["content"]:
                    return og_image["content"]
    except Exception as e:
        print("Error al obtener miniatura:", e)
    return None


async def publish_with_thumbnail(context: ContextTypes.DEFAULT_TYPE, link: str):
    thumb = await fetch_tiktok_thumbnail(link)
    if thumb:
        await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=thumb,
            caption=f"📢 Nuevo video\n{link}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🌐 Ver video", url=link)]])
        )
    else:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=f"⚠️ No se encontró miniatura.\n{link}")

# --- Handler principal ---


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    await publish_text(context, link)
    await publish_with_button(context, link)
    await publish_with_thumbnail(context, link)
    await update.message.reply_text("✅ Se probaron las 3 formas en el canal.")

# --- Configuración de Telegram Application ---
application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND, handle_link))

# --- Endpoint Flask para recibir webhooks ---


@app_flask.route("/", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put_nowait(update)
    return "OK", 200

# --- Inicializar webhook ANTES de arrancar Flask ---


async def init_webhook():
    await application.bot.set_webhook(WEBHOOK_URL)

# Ejecutar inicialización antes de levantar Flask
asyncio.get_event_loop().run_until_complete(init_webhook())

if __name__ == "__main__":
    app_flask.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
