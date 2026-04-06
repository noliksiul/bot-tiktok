import os
import requests
from flask import Flask, request
from bs4 import BeautifulSoup

flask_app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Intenta extraer miniatura real del video (og:image)


def get_tiktok_thumbnail(url):
    try:
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image["content"]:
            return og_image["content"]
    except Exception as e:
        print("❌ Error extrayendo miniatura:", e)
    return None


@flask_app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    print("📥 Payload recibido:", data)

    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]

        if text == "/start":
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": "✅ ¡Webhook directo funcionando en Render!"
            })

        elif text == "/link":
            url_link = "https://vt.tiktok.com/ZSmvnSQDg/"
            reply_markup = {"inline_keyboard": [
                [{"text": "Entrar al link 🔗", "url": url_link}]]}

            # Forma 1: Link directo (Telegram intenta preview, casi nunca funciona)
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"1️⃣ Link directo:\n{url_link}",
                "disable_web_page_preview": False,
                "reply_markup": reply_markup
            })

            # Forma 2: Texto + botón
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": "2️⃣ Texto con botón al enlace",
                "reply_markup": reply_markup
            })

            # Forma 3: Foto personalizada fija
            photo_url = "https://upload.wikimedia.org/wikipedia/commons/0/08/TikTok_logo.png"
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json={
                "chat_id": chat_id,
                "photo": photo_url,
                "caption": f"3️⃣ Miniatura personalizada\n{url_link}",
                "reply_markup": reply_markup
            })

            # Forma 4: Scraping og:image (si TikTok lo permite)
            thumb = get_tiktok_thumbnail(url_link)
            if thumb:
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json={
                    "chat_id": chat_id,
                    "photo": thumb,
                    "caption": f"4️⃣ Miniatura real extraída\n{url_link}",
                    "reply_markup": reply_markup
                })
            else:
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": "4️⃣ No se pudo extraer miniatura real",
                    "reply_markup": reply_markup
                })

            # Forma 5: Imagen servida desde tu servidor (Render)
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json={
                "chat_id": chat_id,
                "photo": "https://tu-app.onrender.com/static/miniatura.jpg",
                "caption": f"5️⃣ Miniatura desde servidor\n{url_link}",
                "reply_markup": reply_markup
            })

            # Forma 6: MediaGroup (álbum con varias imágenes)
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup", json={
                "chat_id": chat_id,
                "media": [
                    {"type": "photo", "media": photo_url,
                        "caption": f"6️⃣ Grupo de medios\n{url_link}"}
                ]
            })

    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
