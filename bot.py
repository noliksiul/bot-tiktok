import os
import requests
from flask import Flask, request

flask_app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # usa variable de entorno en Render

# Handler para /start


@flask_app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    print("📥 Payload recibido:", data)

    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]

        if text == "/start":
            reply = "✅ ¡Webhook directo funcionando en Render!"
        else:
            reply = f"Echo: {text}"

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": reply})

    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
