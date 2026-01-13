import os
import asyncio
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from sqlalchemy import Column, Integer, BigInteger, Text, TIMESTAMP, func, ForeignKey, UniqueConstraint, select, text
from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# --- Configuración DB ---
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()

# --- Tablas ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True)
    tiktok_user = Column(Text)
    balance = Column(Integer, default=10)

class Movimiento(Base):
    __tablename__ = "movimientos"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger)
    detalle = Column(Text)
    puntos = Column(Integer)
    created_at = Column(TIMESTAMP, server_default=func.now())

class Seguimiento(Base):
    __tablename__ = "seguimientos"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger)
    link = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger)
    tipo = Column(Text)
    titulo = Column(Text)
    descripcion = Column(Text)
    link = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())

class Interaccion(Base):
    __tablename__ = "interacciones"
    id = Column(Integer, primary_key=True)
    tipo = Column(Text)   # 'seguimiento' | 'video_support'
    item_id = Column(Integer)
    actor_id = Column(BigInteger)
    owner_id = Column(BigInteger)
    status = Column(Text, default="pending")
    puntos = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())
    __table_args__ = (UniqueConstraint("tipo", "item_id", "actor_id"),)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# --- Config puntos ---
PUNTOS_APOYO_SEGUIMIENTO = 2
PUNTOS_APOYO_VIDEO = 3

# --- Utilidades ---
def back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]]
    )

# --- Handlers básicos ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with async_session() as session:
        user = await session.get(User, update.effective_user.id)
        if not user:
            user = User(telegram_id=update.effective_user.id, balance=10)
            session.add(user)
            await session.commit()
        await update.message.reply_text(
            f"👋 Hola {update.effective_user.first_name}, bienvenido.\n"
            f"Tu balance actual es: {user.balance}",
            reply_markup=back_to_menu_keyboard()
        )
        context.user_data["state"] = "tiktok_user"

async def save_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text.strip()
    async with async_session() as session:
        user = await session.get(User, update.effective_user.id)
        if user:
            user.tiktok_user = tiktok_user
            await session.commit()
    await update.message.reply_text(f"✅ Usuario TikTok registrado: {tiktok_user}", reply_markup=back_to_menu_keyboard())
    context.user_data["state"] = None

async def show_balance(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    async with async_session() as session:
        user = await session.get(User, update_or_query.effective_user.id)
        balance = user.balance if user else 0
        result = await session.execute(
            select(Movimiento).where(Movimiento.telegram_id == update_or_query.effective_user.id).order_by(Movimiento.created_at.desc()).limit(10)
        )
        movimientos = result.scalars().all()
    texto = f"💰 Tu balance actual: {balance} puntos\n\n📜 Últimos movimientos:\n"
    if movimientos:
        for m in movimientos:
            texto += f"- {m.detalle}: {m.puntos} puntos ({m.created_at})\n"
    else:
        texto += "⚠️ No tienes historial todavía."
    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(texto, reply_markup=back_to_menu_keyboard())
    else:
        await update_or_query.edit_message_text(texto, reply_markup=back_to_menu_keyboard())

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_balance(update, context)

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

# --- Handler de texto ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if state == "tiktok_user":
        await save_tiktok(update, context)
    else:
        await update.message.reply_text("⚠️ Usa el menú para interactuar con el bot.", reply_markup=back_to_menu_keyboard())

# --- Main ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")

application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("balance", cmd_balance))
application.add_handler(CallbackQueryHandler(show_main_menu))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

flask_app = Flask(__name__)

@flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "ok"

@flask_app.route("/")
def home():
    return "Bot de Telegram corriendo en Render!"

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        url_path=BOT_TOKEN,
        webhook_url=f"https://{RENDER_EXTERNAL_HOSTNAME}/{BOT_TOKEN}"
    )