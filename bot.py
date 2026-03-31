import os
import requests
from flask import Flask, request

flask_app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN")


@flask_app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    print("📥 Payload recibido:", data)

    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]

        if text == "/link":
            url_link = "https://vt.tiktok.com/ZSmvnSQDg/"

            # Forma 1: Link directo (Telegram intenta mostrar miniatura automática)
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"🔗 Link directo:\n{url_link}",
                "disable_web_page_preview": False
            })

            # Forma 2: Texto + botón
            reply_markup = {
                "inline_keyboard": [[{"text": "Entrar al link 🔗", "url": url_link}]]
            }
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": "👉 Con botón al enlace",
                "reply_markup": reply_markup,
                "disable_web_page_preview": False
            })

            # Forma 3: Foto personalizada como miniatura
            photo_url = "https://upload.wikimedia.org/wikipedia/commons/0/08/TikTok_logo.png"
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json={
                "chat_id": chat_id,
                "photo": photo_url,
                "caption": f"🎬 Miniatura personalizada\n{url_link}",
                "reply_markup": reply_markup
            })

            # Forma 4: Texto con título y descripción manual
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"🎬 Video destacado\nTítulo: Mimo\nDescripción: Prueba de miniatura\n{url_link}",
                "reply_markup": reply_markup,
                "disable_web_page_preview": False
            })

            # Forma 5: Usar sendMediaGroup (varias fotos con el mismo link)
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup", json={
                "chat_id": chat_id,
                "media": [
                    {"type": "photo", "media": photo_url,
                        "caption": f"📸 Grupo de medios\n{url_link}"}
                ]
            })

    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
