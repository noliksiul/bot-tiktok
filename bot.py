import os
import requests
from flask import Flask, request
from bs4 import BeautifulSoup

flask_app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Extrae miniatura real de un enlace (si tiene og:image)


def get_thumbnail(url):
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
                "text": "✅ ¡Webhook funcionando en Render!"
            })

        elif text == "/link":
            # Enlaces a probar
            tiktok_link = "https://vt.tiktok.com/ZSmvnSQDg/"
            youtube_link = "https://www.youtube.com/watch?v=MDHfHuynUnE&list=RDMDHfHuynUnE&start_radio=1"

            # Botón común
            def button(url):
                return {"inline_keyboard": [[{"text": "Entrar al link 🔗", "url": url}]]}

            # --- TikTok ---
            # Forma 1: Link directo
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"1️⃣ TikTok Link directo:\n{tiktok_link}",
                "disable_web_page_preview": False,
                "reply_markup": button(tiktok_link)
            })

            # Forma 2: Texto + botón
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": "2️⃣ TikTok Texto con botón",
                "reply_markup": button(tiktok_link)
            })

            # Forma 3: Foto personalizada fija
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json={
                "chat_id": chat_id,
                "photo": "https://upload.wikimedia.org/wikipedia/commons/0/08/TikTok_logo.png",
                "caption": f"3️⃣ TikTok Miniatura personalizada\n{tiktok_link}",
                "reply_markup": button(tiktok_link)
            })

            # Forma 4: Scraping og:image
            thumb_tiktok = get_thumbnail(tiktok_link)
            if thumb_tiktok:
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json={
                    "chat_id": chat_id,
                    "photo": thumb_tiktok,
                    "caption": f"4️⃣ TikTok Miniatura real extraída\n{tiktok_link}",
                    "reply_markup": button(tiktok_link)
                })
            else:
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": "4️⃣ TikTok no permitió extraer miniatura",
                    "reply_markup": button(tiktok_link)
                })

            # --- YouTube ---
            # Forma 1: Link directo (Telegram sí genera preview)
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": f"1️⃣ YouTube Link directo:\n{youtube_link}",
                "disable_web_page_preview": False,
                "reply_markup": button(youtube_link)
            })

            # Forma 2: Texto + botón
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id": chat_id,
                "text": "2️⃣ YouTube Texto con botón",
                "reply_markup": button(youtube_link)
            })

            # Forma 3: Scraping og:image (miniatura real del video)
            thumb_youtube = get_thumbnail(youtube_link)
            if thumb_youtube:
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json={
                    "chat_id": chat_id,
                    "photo": thumb_youtube,
                    "caption": f"3️⃣ YouTube Miniatura real extraída\n{youtube_link}",
                    "reply_markup": button(youtube_link)
                })

    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
