# --- Módulo 1: Imports y Configuración ---
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions
)
import os
import asyncio
import secrets
from datetime import datetime, timedelta
from flask import Flask, request
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from sqlalchemy import (
    Column, Integer, BigInteger, Text, TIMESTAMP, func,
    UniqueConstraint, select, text, Float
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import aiohttp
from bs4 import BeautifulSoup

# Flask app para webhook
flask_app = Flask(__name__)

# --- Configuración DB ---
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://")
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg://")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()

# --- Config puntos ---
PUNTOS_APOYO_SEGUIMIENTO = 0.5
PUNTOS_APOYO_VIDEO = 0.5
PUNTOS_REFERIDO_BONUS = 0.25

# Lives
PUNTOS_LIVE_SOLO_VER = 0.5
PUNTOS_LIVE_QUIEREME_EXTRA = 1.5
LIVE_VIEW_MINUTES = 5

# --- Canal y grupo ---
CHANNEL_ID = -1003468913370
GROUP_URL = "https://t.me/+9sy0_CwwjnxlOTJh"
CHANNEL_URL = "https://t.me/apoyotiktok002"

# --- Canal de ofertas TikTok Shop ---
CHANNEL_SHOP_ID = -1003664738296
CHANNEL_SHOP_URL = "https://t.me/ofertasimperdiblestiktokshop"

# --- Configuración administrador ---
ADMIN_ID = 890166032

# --- Utilidades UI ---


def back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            "🔙 Regresar al menú principal", callback_data="menu_principal")]]
    )


def yes_no_keyboard(callback_yes: str, callback_no: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Aprobar", callback_data=callback_yes),
         InlineKeyboardButton("❌ Rechazar", callback_data=callback_no)],
        [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal")]
    ])
    # --- Módulo 2: Tablas ---


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    tiktok_user = Column(Text)
    balance = Column(Float, default=10)   # ✅ Float para puntos
    referrer_id = Column(BigInteger, nullable=True, index=True)
    referral_code = Column(Text, unique=True, index=True)
    created_at = Column(TIMESTAMP, server_default=func.now())


class Movimiento(Base):
    __tablename__ = "movimientos"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True)
    detalle = Column(Text)
    puntos = Column(Float)   # ✅ Float
    created_at = Column(TIMESTAMP, server_default=func.now())


class Seguimiento(Base):
    __tablename__ = "seguimientos"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True)
    link = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())


class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True)
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
    actor_id = Column(BigInteger)  # quien apoya
    owner_id = Column(BigInteger)  # dueño del seguimiento/video
    # pending | accepted | rejected | auto_accepted
    status = Column(Text, default="pending")
    puntos = Column(Float, default=0)   # ✅ Float
    created_at = Column(TIMESTAMP, server_default=func.now())
    expires_at = Column(TIMESTAMP)  # fecha límite para auto-aprobar
    __table_args__ = (UniqueConstraint("tipo", "item_id",
                      "actor_id", name="uniq_tipo_item_actor"),)


class SubAdmin(Base):
    __tablename__ = "subadmins"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    created_at = Column(TIMESTAMP, server_default=func.now())


class AdminAction(Base):
    __tablename__ = "admin_actions"
    id = Column(Integer, primary_key=True)
    tipo = Column(Text)   # 'dar_puntos' | 'cambiar_tiktok'
    target_id = Column(BigInteger)
    cantidad = Column(Integer, nullable=True)
    nuevo_alias = Column(Text, nullable=True)
    subadmin_id = Column(BigInteger)
    # pending | accepted | rejected | auto_accepted
    status = Column(Text, default="pending")
    created_at = Column(TIMESTAMP, server_default=func.now())
    expires_at = Column(TIMESTAMP)  # fecha límite para auto-aprobar
    note = Column(Text, nullable=True)


class Live(Base):
    __tablename__ = "lives"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True)  # dueño del live
    link = Column(Text)
    alias = Column(Text, nullable=True)   # ✅ nuevo campo
    puntos = Column(Integer, default=0)   # ✅ nuevo campo
    created_at = Column(TIMESTAMP, server_default=func.now())
    expires_at = Column(TIMESTAMP)   # ✅ nuevo campo para caducidad de 1 día


class Coupon(Base):
    __tablename__ = "coupons"
    id = Column(Integer, primary_key=True)
    code = Column(Text, unique=True)
    total_points = Column(Integer)
    winners_limit = Column(Integer)
    created_by = Column(BigInteger)
    active = Column(Integer, default=1)
    created_at = Column(TIMESTAMP, server_default=func.now())
    # --- Módulo 3: Migración y Helpers ---

# Inicialización DB


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Migración robusta: añadir columnas e índices faltantes


async def migrate_db():
    async with engine.begin() as conn:
        # users: columnas
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT;"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code TEXT;"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();"))
        # users: índices/unique
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_referrer_id ON users(referrer_id);"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_referral_code ON users(referral_code);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);"))

        # users: convertir balance a FLOAT
        await conn.execute(text("ALTER TABLE users ALTER COLUMN balance TYPE FLOAT USING balance::float;"))

        # interacciones: expires_at + índice
        await conn.execute(text("ALTER TABLE interacciones ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_interacciones_status_expires ON interacciones(status, expires_at);"))
        # interacciones: convertir puntos a FLOAT
        await conn.execute(text("ALTER TABLE interacciones ALTER COLUMN puntos TYPE FLOAT USING puntos::float;"))

        # admin_actions: expires_at + índice
        await conn.execute(text("ALTER TABLE admin_actions ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_admin_actions_status_expires ON admin_actions(status, expires_at);"))

        # movimientos: índice por usuario
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_movimientos_telegram_id ON movimientos(telegram_id);"))
        # movimientos: convertir puntos a FLOAT
        await conn.execute(text("ALTER TABLE movimientos ALTER COLUMN puntos TYPE FLOAT USING puntos::float;"))

        # Seguimiento/Video: índices por dueño
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_seguimientos_telegram_id ON seguimientos(telegram_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_videos_telegram_id ON videos(telegram_id);"))

        # Lives: índice por dueño
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_lives_telegram_id ON lives(telegram_id);"))
        # Lives: columnas nuevas
        await conn.execute(text("ALTER TABLE lives ADD COLUMN IF NOT EXISTS alias TEXT;"))
        await conn.execute(text("ALTER TABLE lives ADD COLUMN IF NOT EXISTS puntos INTEGER DEFAULT 0;"))
        await conn.execute(text("ALTER TABLE lives ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;"))

# Helpers de referidos


def build_referral_deeplink(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start=ref_{code}"


async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    me = await context.bot.get_me()
    return me.username

# Notificaciones seguras


async def notify_user(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, reply_markup=None):
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        print("Aviso: no se pudo notificar al usuario:", e)

# Configuración de auto-aprobación
AUTO_APPROVE_INTERVAL_SECONDS = 60
AUTO_APPROVE_AFTER_DAYS = 2
# --- Módulo 4: Menú principal y función Start ---

# Menú principal


async def show_main_menu(update_or_query, context, message="🏠 Menú principal:"):
    # Cancelar cualquier job pendiente antes de reiniciar
    job = context.user_data.get("contenido_job")
    if job:
        job.schedule_removal()
        context.user_data["contenido_job"] = None

    # Reiniciar rotación de contenido al volver al menú
    context.user_data["ultimo_tipo"] = None

    keyboard = [
        [InlineKeyboardButton("📈 Subir seguimiento",
                              callback_data="subir_seguimiento")],
        [InlineKeyboardButton("🎥 Subir video", callback_data="subir_video")],
        [InlineKeyboardButton("📡 Subir live", callback_data="subir_live")],
        [InlineKeyboardButton(
            "👀 Ver contenido", callback_data="ver_contenido")],
        [InlineKeyboardButton("💰 Balance e historial",
                              callback_data="balance")],
        [InlineKeyboardButton("🔗 Mi link de referido",
                              callback_data="mi_ref_link")],
        [InlineKeyboardButton("📊 Estadísticas de referidos",
                              callback_data="resumen_referidos")],
        [InlineKeyboardButton("📋 Comandos", callback_data="comandos")],
        [InlineKeyboardButton("💳 Cobrar cupón", callback_data="cobrar_cupon")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if isinstance(update_or_query, Update) and getattr(update_or_query, "message", None):
        await update_or_query.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(message, reply_markup=reply_markup)


# Función Start con saludo personalizado y menú directo
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args if hasattr(context, "args") else []
    ref_code = None
    if args:
        token = args[0]
        if token.startswith("ref_"):
            ref_code = token.replace("ref_", "").strip()

    async with async_session() as session:
        try:
            res = await session.execute(select(User).where(User.telegram_id == update.effective_user.id))
            user = res.scalars().first()
        except Exception:
            await migrate_db()
            res = await session.execute(select(User).where(User.telegram_id == update.effective_user.id))
            user = res.scalars().first()

        if not user:
            code = secrets.token_urlsafe(6)
            user = User(
                telegram_id=update.effective_user.id,
                balance=10,
                referral_code=code
            )
            if ref_code:
                res_ref = await session.execute(select(User).where(User.referral_code == ref_code))
                referrer = res_ref.scalars().first()
                if referrer and referrer.telegram_id != update.effective_user.id:
                    user.referrer_id = referrer.telegram_id
            session.add(user)
            await session.commit()

            if user.referrer_id:
                await notify_user(
                    context,
                    chat_id=user.referrer_id,
                    text=f"🎉 Nuevo referido: {update.effective_user.id} (@{update.effective_user.username or 'sin_username'}) se registró con tu link.",
                    reply_markup=back_to_menu_keyboard()
                )

    # Bienvenida
    nombre = update.effective_user.first_name or ""
    usuario = f"@{update.effective_user.username}" if update.effective_user.username else ""
    saludo = (
        f"👋 Hola {nombre} {usuario}\n"
        "Bienvenido a la red de apoyo orgánico real diseñada para ti.\n"
        "✨ Espero disfrutes la experiencia."
    )
    await update.message.reply_text(saludo)

    # Botones de canal/grupo
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Ir al canal", url=CHANNEL_URL)],
        [InlineKeyboardButton("👥 Ir al grupo", url=GROUP_URL)],
        [InlineKeyboardButton(
            "🛍️ Ir a ofertas TikTokShop", url=CHANNEL_SHOP_URL)]
    ])
    await update.message.reply_text(
        "📢 Recuerda seguir nuestros canales y grupo para no perderte amistades, promociones y códigos para el bot.",
        reply_markup=keyboard
    )

    # Pedir usuario TikTok si no está registrado
    if not user.tiktok_user:
        await update.message.reply_text(
            "Por favor escribe tu usuario de TikTok (debe comenzar con @).\n"
            "Ejemplo: @lordnolik\n\n"
            "⚠️ Recuerda que si está mal tu usuario pueden rechazar el apoyo y no obtener los puntos."
        )
        context.user_data["state"] = "tiktok_user"
    else:
        await show_main_menu(update, context)
        # --- Módulo 5: Funciones de Seguimiento, Video y Live ---

# Guardar usuario TikTok


async def save_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text.strip()
    if not tiktok_user.startswith("@"):
        await update.message.reply_text(
            "⚠️ Tu usuario de TikTok debe comenzar con @. Ejemplo: @lordnolik",
            reply_markup=back_to_menu_keyboard()
        )
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


# Cambiar usuario TikTok
async def cambiar_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔄 Envía tu nuevo usuario de TikTok (debe comenzar con @). Ejemplo: @lordnolik",
        reply_markup=back_to_menu_keyboard()
    )
    context.user_data["state"] = "cambiar_tiktok"


async def save_new_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text.strip()
    if not tiktok_user.startswith("@"):
        await update.message.reply_text(
            "⚠️ Tu usuario de TikTok debe comenzar con @. Ejemplo: @lordnolik",
            reply_markup=back_to_menu_keyboard()
        )
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


# Subir seguimiento
async def save_seguimiento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    user_id = update.effective_user.id
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user_id))
        user = res.scalars().first()
        if not user:
            await update.message.reply_text("❌ No estás registrado. Usa /start primero.", reply_markup=back_to_menu_keyboard())
            context.user_data["state"] = None
            return
        if (user.balance or 0) < 3:
            await update.message.reply_text("⚠️ No tienes suficientes puntos para subir seguimiento (mínimo 3).", reply_markup=back_to_menu_keyboard())
            context.user_data["state"] = None
            return

        seg = Seguimiento(telegram_id=user_id, link=link)
        session.add(seg)
        user.balance = (user.balance or 0) - 3
        mov = Movimiento(telegram_id=user_id,
                         detalle="Subir seguimiento", puntos=-3)
        session.add(mov)
        await session.commit()

    await update.message.reply_text(
        "✅ Tu seguimiento se subió con éxito.\n\n⚠️ No olvides aceptar o rechazar las solicitudes de seguimiento. "
        "Si en 2 días no lo haces, regalarás tus puntos automáticamente.",
        reply_markup=back_to_menu_keyboard()
    )
    context.user_data["state"] = None

    try:
        alias = user.tiktok_user if user and user.tiktok_user else str(user_id)
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📢 Nuevo seguimiento publicado por {alias}\n🔗 {link}"
        )
    except Exception as e:
        print("Aviso: no se pudo publicar en el canal:", e)


# Subir live con dos modalidades
async def save_live_link(update: Update, context: ContextTypes.DEFAULT_TYPE, tipo="normal"):
    user_id = update.effective_user.id
    link = update.message.text.strip()

    if not link.startswith("http"):
        link = "https://" + link

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user_id))
        u = res.scalars().first()
        if not u:
            await update.message.reply_text("⚠️ No estás registrado en el sistema.", reply_markup=back_to_menu_keyboard())
            return

        costo = 5 if tipo == "normal" else 10
        if (u.balance or 0) < costo:
            await update.message.reply_text(
                f"⚠️ Puntos insuficientes. Necesitas al menos {costo} puntos para subir este live.",
                reply_markup=back_to_menu_keyboard()
            )
            return

        live = Live(
            telegram_id=user_id,
            link=link,
            alias=u.tiktok_user,
            puntos=0,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=1)
        )
        session.add(live)

        u.balance = (u.balance or 0) - costo
        mov = Movimiento(telegram_id=user_id,
                         detalle=f"Subir live ({tipo})", puntos=-costo)
        session.add(mov)

        await session.commit()
        alias = u.tiktok_user
        live_id = live.id

    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                f"🔴 Nuevo live publicado por {alias}\n\n"
                f"⏳ Permanece al menos 2.5 minutos en el live\n\n"
                f"{link}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "👉🚀 Entrar aquí 🔴✨", callback_data=f"abrir_live_{live_id}")],
                [InlineKeyboardButton(
                    "🔙 Regresar al menú principal", callback_data="menu_principal")]
            ])
        )
    except Exception as e:
        print("No se pudo publicar en el canal:", e)

    if tipo == "personalizado":
        async with async_session() as session:
            res = await session.execute(select(User.telegram_id).where(User.telegram_id != user_id))
            todos = res.scalars().all()
            for uid in todos:
                try:
                    live_link = link.strip()
                    if not live_link.startswith("http"):
                        live_link = "https://" + live_link

                    await context.bot.send_message(
                        chat_id=uid,
                        text=(
                            f"📢 Mensaje personalizado de {alias}:\n\n"
                            f"⏳ Permanece al menos 2.5 minutos en el live\n\n"
                            f"{live_link}\n"
                        ),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                "👉🚀 Entrar aquí 🔴✨", callback_data=f"abrir_live_{live_id}")],
                            [InlineKeyboardButton(
                                "🔙 Regresar al menú principal", callback_data="menu_principal")]
                        ])
                    )
                except Exception as e:
                    print(f"No se pudo notificar a {uid}: {e}")

    await update.message.reply_text("✅ Live registrado y notificado.", reply_markup=back_to_menu_keyboard())
    context.user_data["state"] = None
    # --- Módulo 6: Jobs en Background ---

# Auto-aprobación de interacciones pendientes


async def auto_approve_loop(application: Application):
    await asyncio.sleep(5)  # pequeña espera inicial
    while True:
        try:
            async with async_session() as session:
                now = datetime.utcnow()
                res = await session.execute(
                    select(Interaccion).where(
                        Interaccion.status == "pending",
                        Interaccion.expires_at <= now
                    )
                )
                pendings = res.scalars().all()
                for inter in pendings:
                    inter.status = "auto_accepted"
                    # acreditar puntos al actor
                    res_actor = await session.execute(select(User).where(User.telegram_id == inter.actor_id))
                    actor = res_actor.scalars().first()
                    if actor:
                        actor.balance = (actor.balance or 0) + \
                            (inter.puntos or 0)
                        session.add(Movimiento(
                            telegram_id=inter.actor_id,
                            detalle=f"Auto-aprobado {inter.tipo}",
                            puntos=inter.puntos
                        ))
                        # notificar al actor
                        try:
                            await application.bot.send_message(
                                chat_id=inter.actor_id,
                                text=f"✅ Tu apoyo en {inter.tipo} fue auto-aprobado. Ganaste {inter.puntos} puntos.",
                                reply_markup=back_to_menu_keyboard()
                            )
                        except Exception as e:
                            print("Aviso: no se pudo notificar al actor:", e)

                        # bonus referrer
                        if actor.referrer_id:
                            res_ref = await session.execute(select(User).where(User.telegram_id == actor.referrer_id))
                            referrer = res_ref.scalars().first()
                            if referrer:
                                referrer.balance = (
                                    referrer.balance or 0) + PUNTOS_REFERIDO_BONUS
                                session.add(Movimiento(
                                    telegram_id=referrer.telegram_id,
                                    detalle="Bonus por referido (auto-aprobado)",
                                    puntos=PUNTOS_REFERIDO_BONUS
                                ))
                                try:
                                    await application.bot.send_message(
                                        chat_id=referrer.telegram_id,
                                        text=f"💸 Bonus automático: {PUNTOS_REFERIDO_BONUS} puntos por interacción auto-aprobada de tu referido {actor.telegram_id}.",
                                        reply_markup=back_to_menu_keyboard()
                                    )
                                except Exception as e:
                                    print(
                                        "Aviso: no se pudo notificar bonus auto:", e)
                await session.commit()
        except Exception as e:
            print("Error en auto_approve_loop:", e)
        await asyncio.sleep(AUTO_APPROVE_INTERVAL_SECONDS)


# Resumen semanal de referidos
async def referral_weekly_summary_loop(application: Application):
    await asyncio.sleep(10)  # pequeña espera inicial
    while True:
        try:
            async with async_session() as session:
                since = datetime.utcnow() - timedelta(days=7)
                res = await session.execute(
                    select(Movimiento.telegram_id, func.sum(Movimiento.puntos))
                    .where(Movimiento.detalle.like("%Bonus por referido%"))
                    .where(Movimiento.created_at >= since)
                    .group_by(Movimiento.telegram_id)
                )
                rows = res.all()
                for chat_id, total in rows:
                    if total and total > 0:
                        try:
                            await application.bot.send_message(
                                chat_id=chat_id,
                                text=f"📊 Resumen semanal: ganaste {total:.2f} puntos por referidos en los últimos 7 días.",
                                reply_markup=back_to_menu_keyboard()
                            )
                        except Exception as e:
                            print("Aviso: no se pudo enviar resumen semanal:", e)
        except Exception as e:
            print("Error en referral_weekly_summary_loop:", e)
        await asyncio.sleep(3600 * 24 * 7)  # cada semana
        # --- Módulo 7: Main con Webhook en Render ---

BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")


async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers principales
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, save_tiktok))
    application.add_handler(CallbackQueryHandler(
        show_main_menu, pattern="menu_principal"))
    application.add_handler(CallbackQueryHandler(
        save_seguimiento, pattern="subir_seguimiento"))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: save_live_link(u, c, "normal"), pattern="subir_live"))

    # Jobs en background
    asyncio.create_task(auto_approve_loop(application))
    asyncio.create_task(referral_weekly_summary_loop(application))

    # Endpoint Flask para recibir updates
    @flask_app.route("/webhook", methods=["POST"])
    def webhook():
        update = Update.de_json(request.get_json(force=True), application.bot)
        application.update_queue.put_nowait(update)
        return "ok", 200

    # Configurar webhook
    port = int(os.environ.get("PORT", 5000))
    webhook_url = f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
    await application.bot.set_webhook(url=webhook_url)

    # Levantar Flask
    flask_app.run(host="0.0.0.0", port=port)

# --- Ejecución ---
if __name__ == "__main__":
    asyncio.run(main())
