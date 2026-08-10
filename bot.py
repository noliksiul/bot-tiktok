import os
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler

TOKEN = os.getenv("BOT_TOKEN")

# Crear la aplicación de Telegram
application = Application.builder().token(TOKEN).build()

# Handlers de ejemplo


async def start(update: Update, context):
    await update.message.reply_text("Hola DRLL 👋, tu bot ya está funcionando en Render!")

application.add_handler(CommandHandler("start", start))

# Flask app
app = Flask(__name__)


@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    # Usar el loop existente para procesar el update
    asyncio.get_event_loop().create_task(application.process_update(update))
    return "OK"


def start_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def init():
        # Inicializar y arrancar la aplicación
        await application.initialize()
        await application.start()
        await application.bot.set_webhook(
            f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
        )

    loop.run_until_complete(init())
    loop.run_forever()


if __name__ == "__main__":
    # Arrancar el bot en un hilo separado
    import threading
    threading.Thread(target=start_bot, daemon=True).start()
    # Arrancar Flask
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
