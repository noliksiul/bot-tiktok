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

            # Forma 1: Enviar el link directo (Telegram intenta mostrar miniatura)
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

            # Forma 3: Usar sendPhoto con el link como caption
            # aquí puedes poner una imagen fija
            photo_url = "https://p16-sign-va.tiktokcdn.com/tos-maliva-p-0068/..."
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json={
                "chat_id": chat_id,
                "photo": photo_url,
                "caption": f"🎬 Vista previa personalizada\n{url_link}"
            })

            # Forma 4: Texto con título y descripción manual
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"🎬 Video destacado\nTítulo: Mimo\nDescripción: Prueba de miniatura\n{url_link}",
                "disable_web_page_preview": False
            })

    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
