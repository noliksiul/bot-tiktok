import os
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

flask_app = Flask(__name__)
BOT_TOKEN = "6564290496:AAFfyjhNUHMQaryJgMxK-gBNGkJX41Cay0A"

# Handler para /start


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("✅ Handler /start activado")
    if update.message:
        print(f"📩 Mensaje recibido: {update.message.text}")
        await update.message.reply_text("✅ ¡El webhook funciona en Render! Bienvenido al bot.")
    else:
        print("⚠️ Update recibido sin mensaje")


async def main():
    print("🚀 Iniciando aplicación de Telegram...")
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    print("✅ Handler /start registrado")

    @flask_app.route("/webhook", methods=["POST"])
    def webhook():
        try:
            data = request.get_json(force=True)
            print("📥 Payload recibido:", data)  # <-- imprime siempre el JSON
            update = Update.de_json(data, application.bot)
            application.update_queue.put_nowait(update)
            print("📩 Update encolado correctamente")
        except Exception as e:
            print("❌ Error procesando update:", e)
        return "ok", 200

    webhook_url = "https://bot-tiktok-8d3y.onrender.com/webhook"
    await application.bot.set_webhook(url=webhook_url)
    print(f"🔗 Webhook configurado en: {webhook_url}")

    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Flask corriendo en puerto {port}")
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    asyncio.run(main())
