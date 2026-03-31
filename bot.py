import os
import asyncio
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

flask_app = Flask(__name__)
BOT_TOKEN = "6564290496:AAFfyjhNUHMQaryJgMxK-gBNGkJX41Cay0A"

# Handler para /start


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("✅ Handler /start activado")

    # URL que quieres mostrar
    url = "https://vt.tiktok.com/ZSmTVyyLR/"

    # Botón con el link
    keyboard = [[InlineKeyboardButton("Entrar al link 🔗", url=url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Mensaje con vista previa y botón
    await update.message.reply_text(
        f"👉 Aquí está tu enlace:\n{url}",
        reply_markup=reply_markup,
        disable_web_page_preview=False  # esto activa la miniatura/vista previa
    )


async def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))

    @flask_app.route("/webhook", methods=["POST"])
    def webhook():
        update = Update.de_json(request.get_json(force=True), application.bot)
        application.update_queue.put_nowait(update)
        print("📩 Update recibido:", update.to_dict())
        return "ok", 200

    webhook_url = "https://bot-tiktok-8d3y.onrender.com/webhook"
    await application.bot.set_webhook(url=webhook_url)
    print(f"🔗 Webhook configurado en: {webhook_url}")

    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    asyncio.run(main())
