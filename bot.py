import os
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.request import HTTPXRequest

# --- Conexión a Postgres ---
DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# --- Tablas ---
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE,
    tiktok_user TEXT,
    balance INTEGER DEFAULT 10
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS movimientos (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT,
    detalle TEXT,
    puntos INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS seguimientos (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT,
    link TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS videos (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT,
    tipo TEXT,
    titulo TEXT,
    descripcion TEXT,
    link TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS interacciones (
    id SERIAL PRIMARY KEY,
    tipo TEXT,
    item_id INTEGER,
    actor_id BIGINT,
    owner_id BIGINT,
    status TEXT DEFAULT 'pending',
    puntos INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tipo, item_id, actor_id)
)
""")
conn.commit()

# --- Config de puntos ---
PUNTOS_APOYO_SEGUIMIENTO = 2
PUNTOS_APOYO_VIDEO = 3

# --- Utilidades ---
def back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]]
    )

# --- Inicio y registro ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("INSERT INTO users (telegram_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
    conn.commit()
    await update.message.reply_text(
        f"👋 Hola {update.effective_user.first_name}, bienvenido al bot de apoyo TikTok.\n"
        "Por favor escribe tu usuario de TikTok para registrarte.",
        reply_markup=back_to_menu_keyboard()
    )
    context.user_data["state"] = "tiktok_user"

async def save_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text.strip()
    user_id = update.effective_user.id
    if not tiktok_user:
        await update.message.reply_text("⚠️ Envía un usuario válido.", reply_markup=back_to_menu_keyboard())
        return
    cursor.execute("UPDATE users SET tiktok_user=%s WHERE telegram_id=%s", (tiktok_user, user_id))
    conn.commit()
    await show_main_menu(update, context, f"✅ Usuario TikTok registrado: {tiktok_user}")
    context.user_data["state"] = None

# --- Menú principal ---
async def show_main_menu(update_or_query, context, message="🏠 Menú principal:"):
    keyboard = [
        [InlineKeyboardButton("📈 Subir seguimiento", callback_data="subir_seguimiento")],
        [InlineKeyboardButton("🎥 Subir video", callback_data="subir_video")],
        [InlineKeyboardButton("👀 Ver seguimiento", callback_data="ver_seguimiento")],
        [InlineKeyboardButton("📺 Ver video", callback_data="ver_video")],
        [InlineKeyboardButton("💰 Balance e historial", callback_data="balance")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if isinstance(update_or_query, Update) and update_or_query.message:
        await update_or_query.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(message, reply_markup=reply_markup)

# --- Balance e historial ---
async def show_balance(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    is_update = isinstance(update_or_query, Update)
    user_id = (update_or_query.effective_user.id if is_update else update_or_query.from_user.id)

    cursor.execute("INSERT INTO users (telegram_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
    conn.commit()

    cursor.execute("SELECT balance FROM users WHERE telegram_id=%s", (user_id,))
    row = cursor.fetchone()
    balance = row[0] if row else 0

    cursor.execute("""
        SELECT detalle, puntos, created_at
        FROM movimientos
        WHERE telegram_id=%s
        ORDER BY created_at DESC
        LIMIT 10
    """, (user_id,))
    movimientos = cursor.fetchall()

    texto = f"💰 Tu balance actual: {balance} puntos\n\n📜 Últimos movimientos:\n"
    if movimientos:
        for detalle, puntos, fecha in movimientos:
            texto += f"- {detalle}: {puntos} puntos ({fecha})\n"
    else:
        texto += "⚠️ No tienes historial todavía."

    reply_markup = back_to_menu_keyboard()

    if is_update and getattr(update_or_query, "message", None):
        await update_or_query.message.reply_text(texto, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(texto, reply_markup=reply_markup)

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_balance(update, context)

# --- Handler de texto ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    state = context.user_data.get("state")

    if state == "tiktok_user":
        await save_tiktok(update, context)
    else:
        await update.message.reply_text(
            "⚠️ Usa el menú para interactuar con el bot.\n\nSi es tu primera vez, escribe /start.",
            reply_markup=back_to_menu_keyboard()
        )

# --- Main ---
def main():
    token = os.getenv("BOT_TOKEN")  # Token como variable de entorno en Render

    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=10.0,
    )

    app = Application.builder().token(token).request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CallbackQueryHandler(show_main_menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🤖 Bot iniciado y escuchando en Render...")
    app.run_polling(poll_interval=1.0, timeout=30, bootstrap_retries=5, close_loop=False)

if __name__ == "__main__":
    main()