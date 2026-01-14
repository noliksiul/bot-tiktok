# bot.py (Parte 1/3)

import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from sqlalchemy import (
    Column, Integer, BigInteger, Text, TIMESTAMP, func,
    select
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# --- Configuración DB ---
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://")
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()

# --- Tablas ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    tiktok_user = Column(Text)
    balance = Column(Integer, default=10)

class Movimiento(Base):
    __tablename__ = "movimientos"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True)
    detalle = Column(Text)
    puntos = Column(Integer)
    created_at = Column(TIMESTAMP, server_default=func.now())

# --- Inicialización DB ---
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# --- Configuración ---
ADMIN_ID = 890166032
CHANNEL_URL = "https://t.me/apoyotiktok002"
GROUP_URL = "https://t.me/+9sy0_CwwjnxlOTJh"

def back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]]
    )
# bot.py (Parte 2/3)

# --- Menú principal ---
async def show_main_menu(update_or_query, context, message="🏠 Menú principal:"):
    keyboard = [
        [InlineKeyboardButton("💰 Ver balance", callback_data="balance")],
        [InlineKeyboardButton("🔄 Cambiar usuario TikTok", callback_data="cambiar_tiktok")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if isinstance(update_or_query, Update) and getattr(update_or_query, "message", None):
        await update_or_query.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(message, reply_markup=reply_markup)

# --- /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == update.effective_user.id))
        user = res.scalars().first()
        if not user:
            user = User(telegram_id=update.effective_user.id, balance=10)
            session.add(user)
            await session.commit()

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Ir al canal", url=CHANNEL_URL)],
            [InlineKeyboardButton("👥 Ir al grupo", url=GROUP_URL)],
            [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]
        ])
        await update.message.reply_text(
            "📢 Recuerda seguir nuestro canal y grupo para no perderte amistades, promociones y códigos para el bot.",
            reply_markup=keyboard
        )

        await update.message.reply_text(
            f"👋 Hola {update.effective_user.first_name}, tu balance actual es: {user.balance}",
            reply_markup=back_to_menu_keyboard()
        )

        if not user.tiktok_user:
            await update.message.reply_text(
                "Por favor escribe tu usuario de TikTok (debe comenzar con @).",
                reply_markup=back_to_menu_keyboard()
            )
            context.user_data["state"] = "tiktok_user"
        else:
            await show_main_menu(update, context)

# --- Guardar TikTok ---
async def save_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text.strip()
    if not tiktok_user.startswith("@"):
        await update.message.reply_text("⚠️ Tu usuario debe comenzar con @", reply_markup=back_to_menu_keyboard())
        return
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == update.effective_user.id))
        user = res.scalars().first()
        if user:
            user.tiktok_user = tiktok_user
            await session.commit()
    await update.message.reply_text(f"✅ Usuario TikTok registrado: {tiktok_user}", reply_markup=back_to_menu_keyboard())
    context.user_data["state"] = None
    await show_main_menu(update, context)

# --- Cambiar TikTok propio ---
async def cambiar_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Envía tu nuevo usuario TikTok (debe comenzar con @)", reply_markup=back_to_menu_keyboard())
    context.user_data["state"] = "cambiar_tiktok"

async def save_new_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text.strip()
    if not tiktok_user.startswith("@"):
        await update.message.reply_text("⚠️ Tu usuario debe comenzar con @", reply_markup=back_to_menu_keyboard())
        return
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == update.effective_user.id))
        user = res.scalars().first()
        if user:
            user.tiktok_user = tiktok_user
            await session.commit()
    await update.message.reply_text(f"✅ Usuario TikTok actualizado: {tiktok_user}", reply_markup=back_to_menu_keyboard())
    context.user_data["state"] = None
    await show_main_menu(update, context)

# --- Cambiar TikTok de otro (admin) ---
async def cambiar_tiktok_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No tienes permiso para usar este comando.")
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Uso: /cambiar_tiktok_usuario <telegram_id> <@nuevo_usuario>")
        return
    try:
        target_id = int(args[0])
    except:
        await update.message.reply_text("⚠️ <telegram_id> debe ser un número.")
        return
    nuevo_alias = args[1].strip()
    if not nuevo_alias.startswith("@"):
        await update.message.reply_text("⚠️ El usuario debe comenzar con @.")
        return
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == target_id))
        user = res.scalars().first()
        if not user:
            await update.message.reply_text("❌ Usuario no encontrado.")
            return
        user.tiktok_user = nuevo_alias
        await session.commit()
    await update.message.reply_text(f"✅ Usuario TikTok de {target_id} actualizado a: {nuevo_alias}")
# bot.py (Parte 3/3)

# --- Balance ---
async def show_balance(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    user_id = update_or_query.effective_user.id if isinstance(update_or_query, Update) else update_or_query.from_user.id
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user_id))
        user = res.scalars().first()
        balance = user.balance if user else 0
    texto = f"💰 Tu balance actual: {balance} puntos"
    reply_markup = back_to_menu_keyboard()
    if isinstance(update_or_query, Update) and getattr(update_or_query, "message", None):
        await update_or_query.message.reply_text(texto, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(texto, reply_markup=reply_markup)

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_balance(update, context)

# --- Callback ---
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass
    data = query.data
    if data == "menu_principal":
        context.user_data["state"] = None
        await show_main_menu(query, context)
    elif data == "balance":
        await show_balance(query, context)
    elif data == "cambiar_tiktok":
        # soporta venir desde callback
        await cambiar_tiktok(query, context)

# --- Texto ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    state = context.user_data.get("state")
    if state == "tiktok_user":
        await save_tiktok(update, context)
    elif state == "cambiar_tiktok":
        await save_new_tiktok(update, context)
    else:
        await update.message.reply_text(
            "⚠️ Usa el menú para interactuar con el bot.\n\nSi es tu primera vez, escribe /start.",
            reply_markup=back_to_menu_keyboard()
        )

# --- Main (run_webhook sin Flask) ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")

application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("inicio", start))
application.add_handler(CommandHandler("balance", cmd_balance))
application.add_handler(CommandHandler("cambiar_tiktok", cambiar_tiktok))
application.add_handler(CommandHandler("cambiar_tiktok_usuario", cambiar_tiktok_usuario))
application.add_handler(CallbackQueryHandler(menu_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        url_path=BOT_TOKEN,
        webhook_url=f"https://{RENDER_EXTERNAL_HOSTNAME}/{BOT_TOKEN}"
    )
    