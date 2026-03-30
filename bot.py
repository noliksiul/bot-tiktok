import os
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Flask app
flask_app = Flask(__name__)

# Token de tu bot (puedes dejarlo aquí directo o usar variable de entorno en Render)
BOT_TOKEN = "6564290496:AAFfyjhNUHMQaryJgMxK-gBNGkJX41Cay0A"

# Handler de /start


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("📩 Comando /start recibido")  # Log en consola
    await update.message.reply_text("✅ ¡El webhook funciona en Render! Bienvenido al bot.")


async def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))

    # Endpoint Flask para recibir updates
    @flask_app.route("/webhook", methods=["POST"])
    def webhook():
        update = Update.de_json(request.get_json(force=True), application.bot)
        application.update_queue.put_nowait(update)
        print("📩 Update recibido:", update.to_dict())  # Log en consola
        return "ok", 200

    # Configurar webhook explícito con tu dominio de Render
    webhook_url = "https://bot-tiktok-8d3y.onrender.com/webhook"
    await application.bot.set_webhook(url=webhook_url)
    print(f"🔗 Webhook configurado en: {webhook_url}")

    # Levantar Flask
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    asyncio.run(main())
