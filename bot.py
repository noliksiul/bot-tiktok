import os
import asyncio
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

flask_app = Flask(__name__)
BOT_TOKEN = "TU_TOKEN_AQUI"


async def link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://vt.tiktok.com/ZSmTVyyLR/"
    keyboard = [[InlineKeyboardButton("Entrar al link 🔗", url=url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Aquí está tu enlace:\n{url}",
        reply_markup=reply_markup,
        disable_web_page_preview=False  # intenta mostrar miniatura si Telegram lo permite
    )


async def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("link", link))

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
