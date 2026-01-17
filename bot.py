# bot.py (Parte 1/5)

import os
import asyncio
import secrets
from datetime import datetime, timedelta

from sqlalchemy import (
    Column, Integer, BigInteger, Text, TIMESTAMP, func, select, text
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
)

from flask import Flask, request

# --- Ajustes de puntos ---
PUNTOS_APOYO_SEGUIMIENTO = 2
PUNTOS_APOYO_VIDEO = 0.5  # bajado a 0.5
PUNTOS_REFERIDO_BONUS = 0.25
PUNTOS_LIVE_VIEW = 0.5
PUNTOS_LIVE_GIFT_INSTANT = 0.5
PUNTOS_LIVE_GIFT_APPROVAL = 1

AUTO_APPROVE_AFTER_DAYS = 2

# --- Admin principal (tu ID) ---
ADMIN_ID = 890166032

# --- URLs y IDs de canal/grupo ---
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/tu_canal")
GROUP_URL = os.getenv("GROUP_URL", "https://t.me/tu_grupo")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001234567890"))

# --- DB ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:pass@host/db")
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
Base = declarative_base()
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# --- Modelos principales ---
class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    tiktok_user = Column(Text)
    balance = Column(Integer, default=0)
    referral_code = Column(Text)
    referrer_id = Column(BigInteger)
    created_at = Column(TIMESTAMP, server_default=func.now())

class Movimiento(Base):
    __tablename__ = "movimientos"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True)
    detalle = Column(Text)
    puntos = Column(Integer, default=0)
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
    tipo = Column(Text)  # Normal, Incentivo Live, Evento, TikTok Shop, Colaboración
    titulo = Column(Text)
    descripcion = Column(Text)
    link = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())

class Interaccion(Base):
    __tablename__ = "interacciones"
    id = Column(Integer, primary_key=True)
    tipo = Column(Text)  # seguimiento | video_support
    item_id = Column(Integer, index=True)
    actor_id = Column(BigInteger, index=True)
    owner_id = Column(BigInteger, index=True)
    status = Column(Text, default="pending")  # pending|accepted|rejected|auto_accepted
    puntos = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())
    expires_at = Column(TIMESTAMP)

class SubAdmin(Base):
    __tablename__ = "subadmins"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

class AdminAction(Base):
    __tablename__ = "admin_actions"
    id = Column(Integer, primary_key=True)
    tipo = Column(Text)  # dar_puntos | cambiar_tiktok | crear_cupon
    target_id = Column(BigInteger)  # usuario afectado (o 0 para cupon)
    cantidad = Column(Integer)  # para dar_puntos
    nuevo_alias = Column(Text)  # para cambiar_tiktok o payload de cupon "code|reward|winners"
    subadmin_id = Column(BigInteger)
    status = Column(Text, default="pending")
    expires_at = Column(TIMESTAMP)
    note = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())

# --- Lives ---
class Live(Base):
    __tablename__ = "lives"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True)  # dueño del live
    titulo = Column(Text)
    link = Column(Text)  # temporal
    is_active = Column(Integer, default=1)  # 1 activo, 0 inactivo
    created_at = Column(TIMESTAMP, server_default=func.now())

class LiveInteraccion(Base):
    __tablename__ = "live_interacciones"
    id = Column(Integer, primary_key=True)
    live_id = Column(Integer, index=True)
    actor_id = Column(BigInteger, index=True)
    owner_id = Column(BigInteger, index=True)
    tipo = Column(Text)  # 'view' | 'gift'
    status = Column(Text, default="pending")  # para 'gift': pending|accepted|rejected|auto_accepted
    puntos = Column(Integer, default=0)
    started_at = Column(TIMESTAMP)  # para medir 5 min
    created_at = Column(TIMESTAMP, server_default=func.now())
    expires_at = Column(TIMESTAMP)

# --- Cupones ---
class Coupon(Base):
    __tablename__ = "coupons"
    id = Column(Integer, primary_key=True)
    code = Column(Text, unique=True, index=True)  # 4 dígitos
    reward = Column(Integer)  # puntos por cupón
    winners_limit = Column(Integer)  # número de ganadores
    created_by = Column(BigInteger)
    created_at = Column(TIMESTAMP, server_default=func.now())

class CouponClaim(Base):
    __tablename__ = "coupon_claims"
    id = Column(Integer, primary_key=True)
    coupon_id = Column(Integer, index=True)
    claimer_id = Column(BigInteger, index=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

# --- Migración ---
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def migrate_db():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE IF NOT EXISTS lives (id SERIAL PRIMARY KEY, telegram_id BIGINT, titulo TEXT, link TEXT, is_active INT DEFAULT 1, created_at TIMESTAMP DEFAULT NOW());"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_lives_owner ON lives(telegram_id);"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS live_interacciones (id SERIAL PRIMARY KEY, live_id INT, actor_id BIGINT, owner_id BIGINT, tipo TEXT, status TEXT DEFAULT 'pending', puntos INT DEFAULT 0, started_at TIMESTAMP, created_at TIMESTAMP DEFAULT NOW(), expires_at TIMESTAMP);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_live_interacciones_live ON live_interacciones(live_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_live_interacciones_actor ON live_interacciones(actor_id);"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS coupons (id SERIAL PRIMARY KEY, code TEXT UNIQUE, reward INT, winners_limit INT, created_by BIGINT, created_at TIMESTAMP DEFAULT NOW());"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS coupon_claims (id SERIAL PRIMARY KEY, coupon_id INT, claimer_id BIGINT, created_at TIMESTAMP DEFAULT NOW());"))

# --- Utilidades UI ---
def back_to_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]])

def yes_no_keyboard(callback_yes: str, callback_no: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Aprobar", callback_data=callback_yes)],
        [InlineKeyboardButton("❌ Rechazar", callback_data=callback_no)],
        [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal")]
    ])

async def notify_user(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, reply_markup=None):
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        print("notify_user error:", e)

async def notify_admin(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None):
    await notify_user(context, ADMIN_ID, text, reply_markup)

# --- Deep link referido ---
def build_referral_deeplink(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start=ref_{code}"

async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    me = await context.bot.get_me()
    return me.username

# --- Auto-approve loops (interacciones y live gifts) ---
async def auto_approve_loop(application: Application):
    while True:
        try:
            async with async_session() as session:
                now = datetime.utcnow()
                res = await session.execute(select(Interaccion).where(Interaccion.status == "pending").where(Interaccion.expires_at <= now))
                pendings = res.scalars().all()
                for inter in pendings:
                    inter.status = "auto_accepted"
                    res_actor = await session.execute(select(User).where(User.telegram_id == inter.actor_id))
                    actor = res_actor.scalars().first()
                    if actor:
                        actor.balance = (actor.balance or 0) + (inter.puntos or 0)
                        session.add(Movimiento(telegram_id=actor.telegram_id, detalle=f"Auto-aprobado {inter.tipo}", puntos=inter.puntos or 0))
                await session.commit()
        except Exception as e:
            print("auto_approve_loop error:", e)
        await asyncio.sleep(60)

async def referral_weekly_summary_loop(application: Application):
    while True:
        try:
            # placeholder: podrías enviar resúmenes semanales
            pass
        except Exception as e:
            print("referral_weekly_summary_loop error:", e)
        await asyncio.sleep(3600)
# bot.py (Parte 2/5)

# --- Menú principal (actualizado con Lives) ---
async def show_main_menu(update_or_query, context, message="🏠 Menú principal:"):
    async with async_session() as session:
        res = await session.execute(select(func.count()).select_from(Live).where(Live.is_active == 1))
        active_count = res.scalar() or 0

    live_button_text = "🎙️ Ver live"
    if active_count > 0:
        live_button_text = f"🔴 Ver live (en vivo) ✨ ({active_count})"

    keyboard = [
        [InlineKeyboardButton("📈 Subir seguimiento", callback_data="subir_seguimiento")],
        [InlineKeyboardButton("🎥 Subir video", callback_data="subir_video")],
        [InlineKeyboardButton("🎙️ Subir live", callback_data="subir_live")],
        [InlineKeyboardButton(live_button_text, callback_data="ver_live")],
        [InlineKeyboardButton("👀 Ver seguimiento", callback_data="ver_seguimiento")],
        [InlineKeyboardButton("📺 Ver video", callback_data="ver_video")],
        [InlineKeyboardButton("💰 Balance e historial", callback_data="balance")],
        [InlineKeyboardButton("🔗 Mi link de referido", callback_data="mi_ref_link")],
        [InlineKeyboardButton("📋 Comandos", callback_data="comandos")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if isinstance(update_or_query, Update) and getattr(update_or_query, "message", None):
        await update_or_query.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(message, reply_markup=reply_markup)

# --- Start con referido y bienvenida ---
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
                    text=f"🎉 Nuevo referido: {update.effective_user.id} (@{update.effective_user.username or 'sin_username'}) se registró con tu link."
                )

    nombre = update.effective_user.first_name or ""
    usuario = f"@{update.effective_user.username}" if update.effective_user.username else ""
    saludo = (
        f"👋 Hola {nombre} {usuario}\n"
        "Bienvenido a la red de apoyo orgánico real diseñada para ti.\n"
        "✨ Espero disfrutes la experiencia."
    )
    await update.message.reply_text(saludo)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Ir al canal", url=CHANNEL_URL)],
        [InlineKeyboardButton("👥 Ir al grupo", url=GROUP_URL)]
    ])
    await update.message.reply_text(
        "📢 Recuerda seguir nuestro canal y grupo para no perderte amistades, promociones y códigos para el bot.",
        reply_markup=keyboard
    )

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == update.effective_user.id))
        user = res.scalars().first()

    if not user.tiktok_user:
        await update.message.reply_text(
            "Por favor escribe tu usuario de TikTok (debe comenzar con @).\n"
            "Ejemplo: @lordnolik\n\n"
            "⚠️ Recuerda que si está mal tu usuario pueden rechazar el apoyo y no obtener los puntos."
        )
        context.user_data["state"] = "tiktok_user"
    else:
        await show_main_menu(update, context)

# --- Mostrar link de referido ---
async def show_my_ref_link(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(update_or_query, Update):
        user_id = update_or_query.effective_user.id
        is_update = True
    else:
        user_id = update_or_query.from_user.id
        is_update = False

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user_id))
        user = res.scalars().first()

    if not user:
        texto = "❌ No estás registrado. Usa /start primero."
    else:
        bot_username = await get_bot_username(context)
        if not user.referral_code:
            async with async_session() as session:
                res = await session.execute(select(User).where(User.telegram_id == user_id))
                u = res.scalars().first()
                if u and not u.referral_code:
                    u.referral_code = secrets.token_urlsafe(6)
                    await session.commit()
                    user.referral_code = u.referral_code
        deeplink = build_referral_deeplink(bot_username, user.referral_code)
        texto = f"🔗 Tu link de referido:\n{deeplink}\n\nCada interacción aceptada de tus referidos te da {PUNTOS_REFERIDO_BONUS} puntos."

    reply_markup = back_to_menu_keyboard()
    if is_update:
        await update_or_query.message.reply_text(texto, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(texto, reply_markup=reply_markup)

# --- Guardar usuario TikTok ---
async def save_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text.strip()
    if not tiktok_user.startswith("@"):
        await update.message.reply_text(
            "⚠️ Tu usuario de TikTok debe comenzar con @. Ejemplo: @lordnolik\n"
            "Recuerda que si está mal tu usuario pueden rechazar el apoyo y no obtener los puntos.",
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

# --- Cambiar usuario TikTok propio ---
async def cambiar_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔄 Envía tu nuevo usuario de TikTok (debe comenzar con @).\n"
        "Ejemplo: @lordnolik\n\n"
        "⚠️ Recuerda que si está mal tu usuario pueden rechazar el apoyo y no obtener los puntos.",
        reply_markup=back_to_menu_keyboard()
    )
    context.user_data["state"] = "cambiar_tiktok"

async def save_new_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text.strip()
    if not tiktok_user.startswith("@"):
        await update.message.reply_text(
            "⚠️ Tu usuario de TikTok debe comenzar con @. Ejemplo: @lordnolik\n"
            "Recuerda que si está mal tu usuario pueden rechazar el apoyo y no obtener los puntos.",
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

# --- Subir seguimiento ---
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
        mov = Movimiento(telegram_id=user_id, detalle="Subir seguimiento", puntos=-3)
        session.add(mov)
        await session.commit()

    await update.message.reply_text(
        "✅ Tu seguimiento se subió con éxito.\n\n"
        "⚠️ No olvides aceptar o rechazar las solicitudes de seguimiento. "
        "Si en 2 días no lo haces, regalarás tus puntos automáticamente.",
        reply_markup=back_to_menu_keyboard()
    )
    context.user_data["state"] = None

    try:
        alias = user.tiktok_user if user and user.tiktok_user else str(user_id)
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📢 Nuevo seguimiento publicado por {alias}\n🔗 {link}\n\n👉 No olvides seguir nuestro canal de noticias, cupones y promociones."
        )
    except Exception as e:
        print("Aviso: no se pudo publicar en el canal:", e)

# --- Subir video: flujo por pasos ---
async def save_video_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["video_title"] = update.message.text.strip()
    context.user_data["state"] = "video_desc"
    await update.message.reply_text("📝 Ahora envíame la descripción del video:", reply_markup=back_to_menu_keyboard())

async def save_video_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["video_desc"] = update.message.text.strip()
    context.user_data["state"] = "video_link"
    await update.message.reply_text("🔗 Envía el link del video:", reply_markup=back_to_menu_keyboard())

async def save_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    user_id = update.effective_user.id
    tipo = context.user_data.get("video_tipo", "Normal")
    titulo = context.user_data.get("video_title", "")
    descripcion = context.user_data.get("video_desc", "")

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user_id))
        user = res.scalars().first()
        if not user:
            await update.message.reply_text("❌ No estás registrado. Usa /start primero.", reply_markup=back_to_menu_keyboard())
            context.user_data["state"] = None
            return
        if (user.balance or 0) < 5:
            await update.message.reply_text("⚠️ No tienes suficientes puntos para subir video (mínimo 5).", reply_markup=back_to_menu_keyboard())
            context.user_data["state"] = None
            return

        vid = Video(
            telegram_id=user_id,
            tipo=tipo,
            titulo=titulo,
            descripcion=descripcion,
            link=link
        )
        session.add(vid)
        user.balance = (user.balance or 0) - 5
        mov = Movimiento(telegram_id=user_id, detalle="Subir video", puntos=-5)
        session.add(mov)
        await session.commit()

    await update.message.reply_text(
        "✅ Tu video se subió con éxito.\n\n"
        "⚠️ No olvides aceptar o rechazar las solicitudes de apoyo. "
        "Si en 2 días no lo haces, regalarás tus puntos automáticamente.",
        reply_markup=back_to_menu_keyboard()
    )
    context.user_data["state"] = None
    context.user_data["video_title"] = None
    context.user_data["video_desc"] = None
    context.user_data["video_tipo"] = None

    try:
        alias = user.tiktok_user if user and user.tiktok_user else str(user_id)
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📢 Nuevo video ({tipo}) publicado por {alias}\n📌 {titulo}\n📝 {descripcion}\n🔗 {link}"
        )
    except Exception as e:
        print("Aviso: no se pudo publicar en el canal:", e)

# --- Flujo Subir live ---
async def start_subir_live(query, context):
    await query.edit_message_text("🎙️ Envía el título del live:", reply_markup=back_to_menu_keyboard())
    context.user_data["state"] = "live_title"

async def save_live_title(update, context):
    context.user_data["live_title"] = update.message.text.strip()
    context.user_data["state"] = "live_link"
    await update.message.reply_text("🔗 Envía el link temporal del live:", reply_markup=back_to_menu_keyboard())

async def save_live_link(update, context):
    link = update.message.text.strip()
    titulo = context.user_data.get("live_title", "")
    user_id = update.effective_user.id
    async with async_session() as session:
        live = Live(telegram_id=user_id, titulo=titulo, link=link, is_active=1)
        session.add(live)
        await session.commit()
    context.user_data["state"] = None
    context.user_data["live_title"] = None
    await update.message.reply_text("✅ Live registrado como activo. ¡Suerte!", reply_markup=back_to_menu_keyboard())
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=f"🔴 Live activo: {titulo}\n🔗 {link}\n✨ Entra y gana puntos.")
    except Exception as e:
        print("Aviso: no se pudo notificar live al canal:", e)
# bot.py (Parte 3/5)

# --- Ver seguimientos (no propios, solo una vez) ---
async def show_seguimientos(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(update_or_query, Update):
        chat_id = update_or_query.effective_chat.id
        user_id = update_or_query.effective_user.id
    else:
        query = update_or_query
        chat_id = query.message.chat.id
        user_id = query.from_user.id

    async with async_session() as session:
        res = await session.execute(
            select(Seguimiento)
            .where(Seguimiento.telegram_id != user_id)
            .where(~Seguimiento.id.in_(
                select(Interaccion.item_id).where(
                    Interaccion.tipo == "seguimiento",
                    Interaccion.actor_id == user_id
                )
            ))
            .order_by(Seguimiento.created_at.desc())
        )
        rows = res.scalars().all()

    if not rows:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ No hay seguimientos disponibles por ahora.",
            reply_markup=back_to_menu_keyboard()
        )
        return

    seg = rows[0]
    keyboard = [
        [InlineKeyboardButton("🟡 Ya lo seguí ✅", callback_data=f"seguimiento_done_{seg.id}")],
        [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]
    ]
    texto = (
        "👀 Seguimiento disponible:\n"
        f"🔗 {seg.link}\n"
        f"🗓️ {seg.created_at}\n\n"
        "Pulsa el botón si ya seguiste."
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=texto,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- Ver videos (no propios, solo una vez) ---
async def show_videos(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(update_or_query, Update):
        chat_id = update_or_query.effective_chat.id
        user_id = update_or_query.effective_user.id
    else:
        query = update_or_query
        chat_id = query.message.chat.id
        user_id = query.from_user.id

    async with async_session() as session:
        res = await session.execute(
            select(Video)
            .where(Video.telegram_id != user_id)
            .where(~Video.id.in_(
                select(Interaccion.item_id).where(
                    Interaccion.tipo == "video_support",
                    Interaccion.actor_id == user_id
                )
            ))
            .order_by(Video.created_at.desc())
        )
        rows = res.scalars().all()

    if not rows:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ No hay videos disponibles por ahora.",
            reply_markup=back_to_menu_keyboard()
        )
        return

    vid = rows[0]
    keyboard = [
        [InlineKeyboardButton("🟡 Ya apoyé (like/compartir) ⭐", callback_data=f"video_support_done_{vid.id}")],
        [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]
    ]
    texto = (
        f"📺 Video ({vid.tipo}):\n"
        f"📌 {vid.titulo}\n"
        f"📝 {vid.descripcion}\n"
        f"🔗 {vid.link}\n"
        f"🗓️ {vid.created_at}\n\n"
        "⚠️ Si apoyas y luego dejas de seguir, serás candidato a baneo permanente.\n"
        "El apoyo es mutuo y el algoritmo del bot detecta y banea a quienes dejan de seguir.\n\n"
        "❓ Dudas o ayuda: pídelas en el grupo de Telegram.\n\n"
        "Pulsa el botón si ya apoyaste."
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=texto,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- Registrar interacción de seguimiento ---
async def handle_seguimiento_done(query, context: ContextTypes.DEFAULT_TYPE, seg_id: int):
    user_id = query.from_user.id
    async with async_session() as session:
        res_seg = await session.execute(select(Seguimiento).where(Seguimiento.id == seg_id))
        seg = res_seg.scalars().first()
        if not seg:
            await query.edit_message_text("❌ Seguimiento no encontrado.", reply_markup=back_to_menu_keyboard())
            return
        if seg.telegram_id == user_id:
            await query.answer("No puedes apoyar tu propio seguimiento.", show_alert=True)
            return

        expires = datetime.utcnow() + timedelta(days=AUTO_APPROVE_AFTER_DAYS)
        inter = Interaccion(
            tipo="seguimiento",
            item_id=seg.id,
            actor_id=user_id,
            owner_id=seg.telegram_id,
            status="pending",
            puntos=PUNTOS_APOYO_SEGUIMIENTO,
            expires_at=expires
        )
        session.add(inter)
        await session.commit()

        res_actor = await session.execute(select(User).where(User.telegram_id == user_id))
        actor = res_actor.scalars().first()

    await query.edit_message_text("🟡 Tu apoyo fue registrado y está pendiente de aprobación del dueño.", reply_markup=back_to_menu_keyboard())
    await notify_user(
        context,
        chat_id=seg.telegram_id,
        text=(
            f"📩 Nuevo apoyo a tu seguimiento:\n"
            f"Item ID: {seg.id}\n"
            f"Actor: {user_id}\n"
            f"Usuario TikTok: {actor.tiktok_user or 'no registrado'}\n"
            f"Puntos: {PUNTOS_APOYO_SEGUIMIENTO}\n\n"
            "¿Apruebas?"
        ),
        reply_markup=yes_no_keyboard(
            callback_yes=f"approve_interaction_{inter.id}",
            callback_no=f"reject_interaction_{inter.id}"
        )
    )

# --- Registrar interacción de video ---
async def handle_video_support_done(query, context: ContextTypes.DEFAULT_TYPE, vid_id: int):
    user_id = query.from_user.id
    async with async_session() as session:
        res_vid = await session.execute(select(Video).where(Video.id == vid_id))
        vid = res_vid.scalars().first()
        if not vid:
            await query.edit_message_text("❌ Video no encontrado.", reply_markup=back_to_menu_keyboard())
            return
        if vid.telegram_id == user_id:
            await query.answer("No puedes apoyar tu propio video.", show_alert=True)
            return

        expires = datetime.utcnow() + timedelta(days=AUTO_APPROVE_AFTER_DAYS)
        inter = Interaccion(
            tipo="video_support",
            item_id=vid.id,
            actor_id=user_id,
            owner_id=vid.telegram_id,
            status="pending",
            puntos=PUNTOS_APOYO_VIDEO,
            expires_at=expires
        )
        session.add(inter)
        await session.commit()

        res_actor = await session.execute(select(User).where(User.telegram_id == user_id))
        actor = res_actor.scalars().first()

    await query.edit_message_text("🟡 Tu apoyo fue registrado y está pendiente de aprobación del dueño.", reply_markup=back_to_menu_keyboard())
    await notify_user(
        context,
        chat_id=vid.telegram_id,
        text=(
            f"📩 Nuevo apoyo a tu video:\n"
            f"Item ID: {vid.id}\n"
            f"Actor: {user_id}\n"
            f"Usuario TikTok: {actor.tiktok_user or 'no registrado'}\n"
            f"Puntos: {PUNTOS_APOYO_VIDEO}\n\n"
            "¿Apruebas?"
        ),
        reply_markup=yes_no_keyboard(
            callback_yes=f"approve_interaction_{inter.id}",
            callback_no=f"reject_interaction_{inter.id}"
        )
    )

# --- Aprobar interacción ---
async def approve_interaction(query, context: ContextTypes.DEFAULT_TYPE, inter_id: int):
    async with async_session() as session:
        res = await session.execute(select(Interaccion).where(Interaccion.id == inter_id))
        inter = res.scalars().first()
        if not inter:
            await query.edit_message_text("❌ Interacción no encontrada.", reply_markup=back_to_menu_keyboard())
            await show_main_menu(query, context)
            return

        if query.from_user.id != inter.owner_id:
            await query.answer("No puedes aprobar esta interacción.", show_alert=True)
            return
        if inter.status != "pending":
            await query.edit_message_text(f"⚠️ Esta interacción ya está en estado: {inter.status}.", reply_markup=back_to_menu_keyboard())
            await show_main_menu(query, context)
            return

        inter.status = "accepted"
        res_actor = await session.execute(select(User).where(User.telegram_id == inter.actor_id))
        actor = res_actor.scalars().first()
        if actor:
            actor.balance = (actor.balance or 0) + (inter.puntos or 0)
            mov = Movimiento(telegram_id=inter.actor_id, detalle=f"Apoyo {inter.tipo} aprobado", puntos=inter.puntos)
            session.add(mov)
            if actor.referrer_id:
                res_ref = await session.execute(select(User).where(User.telegram_id == actor.referrer_id))
                referrer = res_ref.scalars().first()
                if referrer:
                    referrer.balance = (referrer.balance or 0) + PUNTOS_REFERIDO_BONUS
                    session.add(Movimiento(
                        telegram_id=referrer.telegram_id,
                        detalle="Bonus por referido",
                        puntos=PUNTOS_REFERIDO_BONUS
                    ))
                    await notify_user(
                        context,
                        chat_id=referrer.telegram_id,
                        text=f"💸 Recibiste {PUNTOS_REFERIDO_BONUS} puntos por la interacción aceptada de tu referido {actor.telegram_id}."
                    )
        await session.commit()

    await query.edit_message_text("✅ Interacción aprobada. Puntos otorgados.", reply_markup=back_to_menu_keyboard())
    await show_main_menu(query, context)
    await notify_user(context, chat_id=inter.actor_id, text=f"✅ Tu apoyo en {inter.tipo} fue aprobado. Ganaste {inter.puntos} puntos.", reply_markup=back_to_menu_keyboard())

# --- Rechazar interacción ---
async def reject_interaction(query, context: ContextTypes.DEFAULT_TYPE, inter_id: int):
    async with async_session() as session:
        res = await session.execute(select(Interaccion).where(Interaccion.id == inter_id))
        inter = res.scalars().first()
        if not inter:
            await query.edit_message_text("❌ Interacción no encontrada.", reply_markup=back_to_menu_keyboard())
            await show_main_menu(query, context)
            return

        if query.from_user.id != inter.owner_id:
            await query.answer("No puedes rechazar esta interacción.", show_alert=True)
            return
        if inter.status != "pending":
            await query.edit_message_text(f"⚠️ Esta interacción ya está en estado: {inter.status}.", reply_markup=back_to_menu_keyboard())
            await show_main_menu(query, context)
            return

        inter.status = "rejected"
        await session.commit()

    await query.edit_message_text("❌ Interacción rechazada.", reply_markup=back_to_menu_keyboard())
    await show_main_menu(query, context)
    await notify_user(context, chat_id=inter.actor_id, text=f"❌ Tu apoyo en {inter.tipo} fue rechazado.", reply_markup=back_to_menu_keyboard())

# --- Ver lives (no propios) ---
async def show_lives(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(update_or_query, Update):
        chat_id = update_or_query.effective_chat.id
        user_id = update_or_query.effective_user.id
    else:
        query = update_or_query
        chat_id = query.message.chat.id
        user_id = query.from_user.id

    async with async_session() as session:
        res = await session.execute(
            select(Live).where(Live.is_active == 1).where(Live.telegram_id != user_id).order_by(Live.created_at.desc())
        )
        lives = res.scalars().all()

    if not lives:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ No hay lives activos por ahora.", reply_markup=back_to_menu_keyboard())
        return

    live = lives[0]
    context.user_data["live_view"] = {"live_id": live.id, "start_time": datetime.utcnow()}
    keyboard = [
        [InlineKeyboardButton("⏱️ Estuve 5 min", callback_data=f"live_view_done_{live.id}")],
        [InlineKeyboardButton("🎁 Di el quiereme", callback_data=f"live_gift_done_{live.id}")],
        [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]
    ]
    texto = (
        f"🔴 Live:\n"
        f"📌 {live.titulo}\n"
        f"🔗 {live.link}\n\n"
        "Debes estar 5 minutos en el live.\n"
        f"• Vista 5 min: +{PUNTOS_LIVE_VIEW} puntos.\n"
        f"• Gift 'Quiéreme': +{PUNTOS_LIVE_GIFT_INSTANT} inmediato y, tras aprobación del dueño, +{PUNTOS_LIVE_GIFT_APPROVAL} extra.\n\n"
        "Pulsa el botón correspondiente cuando cumplas."
    )
    await context.bot.send_message(chat_id=chat_id, text=texto, reply_markup=InlineKeyboardMarkup(keyboard))

# --- Completar vista de 5 min ---
async def handle_live_view_done(query, context, live_id: int):
    user_id = query.from_user.id
    data = context.user_data.get("live_view", {})
    start = data.get("start_time")
    if not start or data.get("live_id") != live_id:
        await query.answer("No detecté tu inicio de live. Entra de nuevo a 'Ver live'.", show_alert=True)
        return
    elapsed = (datetime.utcnow() - start).total_seconds()
    if elapsed < 300:
        faltan = int(300 - elapsed)
        await query.answer(f"Te faltan {faltan} segundos para completar 5 min.", show_alert=True)
        return

    async with async_session() as session:
        res_live = await session.execute(select(Live).where(Live.id == live_id))
        live = res_live.scalars().first()
        if not live:
            await query.edit_message_text("❌ Live no encontrado.", reply_markup=back_to_menu_keyboard())
            return
        res_actor = await session.execute(select(User).where(User.telegram_id == user_id))
        actor = res_actor.scalars().first()
        if actor:
            actor.balance = (actor.balance or 0) + PUNTOS_LIVE_VIEW
            session.add(Movimiento(telegram_id=user_id, detalle="Vista de live (5 min)", puntos=PUNTOS_LIVE_VIEW))
        session.add(LiveInteraccion(
            live_id=live_id, actor_id=user_id, owner_id=live.telegram_id,
            tipo="view", status="accepted", puntos=PUNTOS_LIVE_VIEW, started_at=start
        ))
        await session.commit()

    context.user_data["live_view"] = None
    await query.edit_message_text("✅ Vista de 5 min acreditada (+0.5).", reply_markup=back_to_menu_keyboard())
    await show_main_menu(query, context)

# --- Completar gift 'Quiéreme' ---
async def handle_live_gift_done(query, context, live_id: int):
    user_id = query.from_user.id
    async with async_session() as session:
        res_live = await session.execute(select(Live).where(Live.id == live_id))
        live = res_live.scalars().first()
        if not live:
            await query.edit_message_text("❌ Live no encontrado.", reply_markup=back_to_menu_keyboard())
            return
        res_actor = await session.execute(select(User).where(User.telegram_id == user_id))
        actor = res_actor.scalars().first()
        if actor:
            actor.balance = (actor.balance or 0) + PUNTOS_LIVE_GIFT_INSTANT
            session.add(Movimiento(telegram_id=user_id, detalle="Gift 'Quiéreme' (instantáneo)", puntos=PUNTOS_LIVE_GIFT_INSTANT))
        expires = datetime.utcnow() + timedelta(days=AUTO_APPROVE_AFTER_DAYS)
        inter = LiveInteraccion(
            live_id=live_id, actor_id=user_id, owner_id=live.telegram_id,
            tipo="gift", status="pending", puntos=PUNTOS_LIVE_GIFT_APPROVAL,
            started_at=datetime.utcnow(), expires_at=expires
        )
        session.add(inter)
        await session.commit()

    await query.edit_message_text("🟡 Gift registrado. Recibiste +0.5. El dueño debe aprobar para +1 extra.", reply_markup=back_to_menu_keyboard())
    await notify_user(
        context,
        chat_id=live.telegram_id,
        text=(
            f"📩 Nuevo gift en tu live:\n"
            f"Live ID: {live.id}\n"
            f"Actor: {user_id}\n"
            f"Puntos extra propuestos: {PUNTOS_LIVE_GIFT_APPROVAL}\n\n"
            "¿Apruebas?"
        ),
        reply_markup=yes_no_keyboard(
            callback_yes=f"approve_live_gift_{inter.id}",
            callback_no=f"reject_live_gift_{inter.id}"
        )
    )

# --- Aprobar gift de live ---
async def approve_live_gift(query, context, inter_id: int):
    async with async_session() as session:
        res = await session.execute(select(LiveInteraccion).where(LiveInteraccion.id == inter_id))
        inter = res.scalars().first()
        if not inter:
            await query.edit_message_text("❌ Interacción de live no encontrada.", reply_markup=back_to_menu_keyboard())
            return
        if query.from_user.id != inter.owner_id:
            await query.answer("No puedes aprobar este gift.", show_alert=True)
            return
        if inter.status != "pending":
            await query.edit_message_text(f"⚠️ Ya está en estado: {inter.status}.", reply_markup=back_to_menu_keyboard())
            return

        inter.status = "accepted"
        res_actor = await session.execute(select(User).where(User.telegram_id == inter.actor_id))
        actor = res_actor.scalars().first()
        if actor:
            actor.balance = (actor.balance or 0) + PUNTOS_LIVE_GIFT_APPROVAL
            session.add(Movimiento(telegram_id=actor.telegram_id, detalle="Gift 'Quiéreme' aprobado (+1)", puntos=PUNTOS_LIVE_GIFT_APPROVAL))
        await session.commit()

    await query.edit_message_text("✅ Gift aprobado. +1 acreditado.", reply_markup=back_to_menu_keyboard())
    await notify_user(context, chat_id=inter.actor_id, text="✅ Tu gift fue aprobado. +1 punto extra.")

# --- Rechazar gift de live ---
async def reject_live_gift(query, context, inter_id: int):
    async with async_session() as session:
        res = await session.execute(select(LiveInteraccion).where(LiveInteraccion.id == inter_id))
        inter = res.scalars().first()
        if not inter:
            await query.edit_message_text("❌ Interacción de live no encontrada.", reply_markup=back_to_menu_keyboard())
            return
        if query.from_user.id != inter.owner_id:
            await query.answer("No puedes rechazar este gift.", show_alert=True)
            return
        if inter.status != "pending":
            await query.edit_message_text(f"⚠️ Ya está en estado: {inter.status}.", reply_markup=back_to_menu_keyboard())
            return

        inter.status = "rejected"
        await session.commit()

    await query.edit_message_text("❌ Gift rechazado.", reply_markup=back_to_menu_keyboard())
    await notify_user(context, chat_id=inter.actor_id, text="❌ Tu gift fue rechazado.")
# bot.py (Parte 4/5)

# --- Balance e historial ---
async def show_balance(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(update_or_query, Update):
        user_id = update_or_query.effective_user.id
        is_update = True
    else:
        user_id = update_or_query.from_user.id
        is_update = False

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user_id))
        user = res.scalars().first()
        balance = user.balance if user else 0
        res = await session.execute(
            select(Movimiento)
            .where(Movimiento.telegram_id == user_id)
            .order_by(Movimiento.created_at.desc())
            .limit(10)
        )
        movimientos = res.scalars().all()

    texto = f"💰 Tu balance actual: {balance} puntos\n\n📜 Últimos movimientos:\n"
    if movimientos:
        for m in movimientos:
            texto += f"- {m.detalle}: {m.puntos} puntos ({m.created_at})\n"
    else:
        texto += "⚠️ No tienes historial todavía."

    reply_markup = back_to_menu_keyboard()
    if is_update:
        await update_or_query.message.reply_text(texto, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(texto, reply_markup=reply_markup)

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_balance(update, context)

# --- Listar usuarios (coronas) ---
async def listar_usuarios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No tienes permiso para usar este comando.")
        return

    async with async_session() as session:
        res = await session.execute(select(User))
        usuarios = res.scalars().all()
        res_sub = await session.execute(select(SubAdmin))
        subs = {s.telegram_id for s in res_sub.scalars().all()}

    if not usuarios:
        await update.message.reply_text("⚠️ No hay usuarios registrados.")
        return

    texto = "👥 Usuarios registrados:\n"
    for u in usuarios:
        crown = ""
        if u.telegram_id == ADMIN_ID:
            crown = " 👑(principal)"
        elif u.telegram_id in subs:
            crown = " 👑(secundario)"
        texto += f"- ID: {u.telegram_id}{crown}, TikTok: {u.tiktok_user}, Balance: {u.balance}, Referrer: {u.referrer_id}\n"

    await update.message.reply_text(texto)

# --- Gestión de SubAdmins ---
async def add_subadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No tienes permiso para usar este comando.")
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Uso: /add_subadmin <telegram_id>")
        return
    try:
        sub_id = int(args[0])
    except:
        await update.message.reply_text("⚠️ <telegram_id> debe ser un número.")
        return
    async with async_session() as session:
        res = await session.execute(select(SubAdmin).where(SubAdmin.telegram_id == sub_id))
        exists = res.scalars().first()
        if exists:
            await update.message.reply_text("⚠️ Ya es subadmin.")
            return
        session.add(SubAdmin(telegram_id=sub_id))
        await session.commit()
    await update.message.reply_text(f"✅ Subadmin agregado: {sub_id}")
    await notify_user(
        context,
        chat_id=sub_id,
        text=(
            "🎉 Has sido promovido a Subadmin.\n\n"
            "Tendrás acceso a los comandos de administración.\n"
            "⚠️ Las acciones de 'dar puntos' y 'cambiar TikTok' requieren autorización del admin principal.\n"
            "Cada solicitud que hagas será notificada al admin para aprobación."
        )
    )

async def remove_subadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No tienes permiso para usar este comando.")
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Uso: /remove_subadmin <telegram_id>")
        return
    try:
        sub_id = int(args[0])
    except:
        await update.message.reply_text("⚠️ <telegram_id> debe ser un número.")
        return
    async with async_session() as session:
        res = await session.execute(select(SubAdmin).where(SubAdmin.telegram_id == sub_id))
        sub = res.scalars().first()
        if not sub:
            await update.message.reply_text("⚠️ No es subadmin.")
            return
        await session.delete(sub)
        await session.commit()
    await update.message.reply_text(f"✅ Subadmin eliminado: {sub_id}")

async def is_subadmin(user_id: int) -> bool:
    async with async_session() as session:
        res = await session.execute(select(SubAdmin).where(SubAdmin.telegram_id == user_id))
        return res.scalars().first() is not None

# --- Acciones administrativas propuestas por subadmin ---
async def dar_puntos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_subadmin(user_id) and user_id != ADMIN_ID:
        await update.message.reply_text("❌ No tienes permiso para proponer esta acción.")
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Uso: /dar_puntos <telegram_id> <cantidad>")
        return
    try:
        target_id = int(args[0])
        cantidad = float(args[1])
    except:
        await update.message.reply_text("⚠️ Ambos parámetros deben ser números.")
        return

    if user_id == ADMIN_ID:
        async with async_session() as session:
            res_u = await session.execute(select(User).where(User.telegram_id == target_id))
            u = res_u.scalars().first()
            if not u:
                await update.message.reply_text("❌ Usuario no encontrado.")
                return
            u.balance = (u.balance or 0) + cantidad
            session.add(Movimiento(telegram_id=u.telegram_id, detalle=f"Puntos otorgados por admin ({cantidad})", puntos=cantidad))
            await session.commit()
        await update.message.reply_text(f"✅ Puntos otorgados: {cantidad} a {target_id}.")
        return

    expires = datetime.utcnow() + timedelta(days=AUTO_APPROVE_AFTER_DAYS)
    async with async_session() as session:
        action = AdminAction(
            tipo="dar_puntos",
            target_id=target_id,
            cantidad=int(cantidad),
            subadmin_id=user_id,
            status="pending",
            expires_at=expires,
            note=f"Propuesto por {user_id}"
        )
        session.add(action)
        await session.commit()

    await update.message.reply_text(f"🟡 Acción propuesta: dar {cantidad} puntos a {target_id}. Pendiente de aprobación del admin.")
    await notify_admin(context, text=f"🟡 Acción pendiente: dar {cantidad} puntos a {target_id} (propuesta por {user_id}).")

async def cambiar_tiktok_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_subadmin(user_id) and user_id != ADMIN_ID:
        await update.message.reply_text("❌ No tienes permiso para proponer esta acción.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Uso: /cambiar_tiktok_usuario <telegram_id> <nuevo_alias_con_@>")
        return
    try:
        target_id = int(args[0])
    except:
        await update.message.reply_text("⚠️ <telegram_id> debe ser un número.")
        return
    nuevo_alias = " ".join(args[1:]).strip()
    if not nuevo_alias.startswith("@"):
        await update.message.reply_text("⚠️ El alias debe comenzar con @.")
        return

    if user_id == ADMIN_ID:
        async with async_session() as session:
            res_u = await session.execute(select(User).where(User.telegram_id == target_id))
            u = res_u.scalars().first()
            if not u:
                await update.message.reply_text("❌ Usuario no encontrado.")
                return
            u.tiktok_user = nuevo_alias
            await session.commit()
        await update.message.reply_text(f"✅ TikTok actualizado para {target_id}: {nuevo_alias}")
        return

    expires = datetime.utcnow() + timedelta(days=AUTO_APPROVE_AFTER_DAYS)
    async with async_session() as session:
        action = AdminAction(
            tipo="cambiar_tiktok",
            target_id=target_id,
            nuevo_alias=nuevo_alias,
            subadmin_id=user_id,
            status="pending",
            expires_at=expires,
            note=f"Propuesto por {user_id}"
        )
        session.add(action)
        await session.commit()

    await update.message.reply_text(f"🟡 Acción propuesta: cambiar TikTok de {target_id} a {nuevo_alias}. Pendiente de aprobación del admin.")
    await notify_admin(context, text=f"🟡 Acción pendiente: cambiar TikTok de {target_id} a {nuevo_alias} (propuesta por {user_id}).")

# --- Aprobar/Rechazar acciones administrativas ---
async def approve_admin_action(query, context: ContextTypes.DEFAULT_TYPE, action_id: int):
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Solo el admin puede aprobar.", show_alert=True)
        return
    async with async_session() as session:
        res = await session.execute(select(AdminAction).where(AdminAction.id == action_id))
        action = res.scalars().first()
        if not action:
            await query.edit_message_text("❌ Acción no encontrada.", reply_markup=back_to_menu_keyboard())
            return
        if action.status != "pending":
            await query.edit_message_text(f"⚠️ Acción ya está en estado: {action.status}.", reply_markup=back_to_menu_keyboard())
            return

        if action.tipo == "dar_puntos":
            res_u = await session.execute(select(User).where(User.telegram_id == action.target_id))
            u = res_u.scalars().first()
            if u:
                u.balance = (u.balance or 0) + (action.cantidad or 0)
                session.add(Movimiento(
                    telegram_id=u.telegram_id,
                    detalle=f"Puntos otorgados por admin ({action.cantidad})",
                    puntos=action.cantidad or 0
                ))
        elif action.tipo == "cambiar_tiktok":
            res_u = await session.execute(select(User).where(User.telegram_id == action.target_id))
            u = res_u.scalars().first()
            if u and action.nuevo_alias:
                u.tiktok_user = action.nuevo_alias
        elif action.tipo == "crear_cupon":
            parts = (action.nuevo_alias or "").split("|")
            if len(parts) == 3:
                code, reward, winners = parts[0], float(parts[1]), int(parts[2])
                res_exist = await session.execute(select(Coupon).where(Coupon.code == code))
                if not res_exist.scalars().first():
                    session.add(Coupon(code=code, reward=reward, winners_limit=winners, created_by=action.subadmin_id))

        action.status = "accepted"
        await session.commit()

    await query.edit_message_text("✅ Acción administrativa aprobada y aplicada.", reply_markup=back_to_menu_keyboard())

async def reject_admin_action(query, context: ContextTypes.DEFAULT_TYPE, action_id: int):
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Solo el admin puede rechazar.", show_alert=True)
        return
    async with async_session() as session:
        res = await session.execute(select(AdminAction).where(AdminAction.id == action_id))
        action = res.scalars().first()
        if not action:
            await query.edit_message_text("❌ Acción no encontrada.", reply_markup=back_to_menu_keyboard())
            return
        if action.status != "pending":
            await query.edit_message_text(f"⚠️ Acción ya está en estado: {action.status}.", reply_markup=back_to_menu_keyboard())
            return

        action.status = "rejected"
        await session.commit()

    await query.edit_message_text("❌ Acción administrativa rechazada.", reply_markup=back_to_menu_keyboard())
# bot.py (Parte 5/5)

# --- Callback principal (menú y acciones) ---
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass

    data = query.data

    if data == "subir_seguimiento":
        await query.edit_message_text(
            "🔗 Envía tu link de perfil de TikTok para publicar tu seguimiento (costo: 3 puntos).",
            reply_markup=back_to_menu_keyboard()
        )
        context.user_data["state"] = "seguimiento_link"

    elif data == "subir_video":
        keyboard = [
            [InlineKeyboardButton("🎬 Normal", callback_data="video_tipo_normal")],
            [InlineKeyboardButton("🎤 Incentivo Live", callback_data="video_tipo_live")],
            [InlineKeyboardButton("🎉 Evento", callback_data="video_tipo_evento")],
            [InlineKeyboardButton("🛍️ TikTok Shop", callback_data="video_tipo_shop")],
            [InlineKeyboardButton("🤝 Colaboración", callback_data="video_tipo_colaboracion")],
            [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]
        ]
        await query.edit_message_text("📌 ¿Qué tipo de video quieres subir?", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["state"] = None

    elif data.startswith("video_tipo_"):
        tipos = {
            "video_tipo_normal": "Normal",
            "video_tipo_live": "Incentivo Live",
            "video_tipo_evento": "Evento",
            "video_tipo_shop": "TikTok Shop",
            "video_tipo_colaboracion": "Colaboración"
        }
        context.user_data["video_tipo"] = tipos.get(data, "Normal")
        context.user_data["state"] = "video_title"
        await query.edit_message_text(
            f"🎬 Tipo seleccionado: {context.user_data['video_tipo']}\n\nAhora envíame el título de tu video:",
            reply_markup=back_to_menu_keyboard()
        )

    elif data == "subir_live":
        await start_subir_live(query, context)

    elif data == "ver_live":
        await show_lives(query, context)

    elif data == "ver_seguimiento":
        await show_seguimientos(query, context)

    elif data == "ver_video":
        await show_videos(query, context)

    elif data == "balance":
        await show_balance(query, context)

    elif data == "mi_ref_link":
        await show_my_ref_link(query, context)

    elif data == "comandos":
        await comandos(query, context)

    elif data.startswith("seguimiento_done_"):
        seg_id = int(data.split("_")[-1])
        await handle_seguimiento_done(query, context, seg_id)

    elif data.startswith("video_support_done_"):
        vid_id = int(data.split("_")[-1])
        await handle_video_support_done(query, context, vid_id)

    elif data.startswith("approve_interaction_"):
        inter_id = int(data.split("_")[-1])
        await approve_interaction(query, context, inter_id)

    elif data.startswith("reject_interaction_"):
        inter_id = int(data.split("_")[-1])
        await reject_interaction(query, context, inter_id)

    elif data.startswith("live_view_done_"):
        live_id = int(data.split("_")[-1])
        await handle_live_view_done(query, context, live_id)

    elif data.startswith("live_gift_done_"):
        live_id = int(data.split("_")[-1])
        await handle_live_gift_done(query, context, live_id)

    elif data.startswith("approve_live_gift_"):
        inter_id = int(data.split("_")[-1])
        await approve_live_gift(query, context, inter_id)

    elif data.startswith("reject_live_gift_"):
        inter_id = int(data.split("_")[-1])
        await reject_live_gift(query, context, inter_id)

    elif data.startswith("approve_admin_action_"):
        action_id = int(data.split("_")[-1])
        await approve_admin_action(query, context, action_id)

    elif data.startswith("reject_admin_action_"):
        action_id = int(data.split("_")[-1])
        await reject_admin_action(query, context, action_id)

    elif data == "menu_principal":
        context.user_data["state"] = None
        await show_main_menu(query, context)

# --- Handler de texto principal ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    state = context.user_data.get("state")
    if state == "tiktok_user":
        await save_tiktok(update, context)
    elif state == "cambiar_tiktok":
        await save_new_tiktok(update, context)
    elif state == "seguimiento_link":
        await save_seguimiento(update, context)
    elif state == "video_title":
        await save_video_title(update, context)
    elif state == "video_desc":
        await save_video_desc(update, context)
    elif state == "video_link":
        await save_video_link(update, context)
    elif state == "live_title":
        await save_live_title(update, context)
    elif state == "live_link":
        await save_live_link(update, context)
    else:
        await update.message.reply_text(
            "⚠️ Usa el menú para interactuar con el bot.\n\nSi es tu primera vez, escribe /start.",
            reply_markup=back_to_menu_keyboard()
        )

# --- Comando: lista de comandos ---
async def comandos(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "📋 Lista de comandos disponibles:\n\n"
        "👤 Usuario:\n"
        "• /start - Iniciar bot\n"
        "• /balance - Ver balance\n"
        "• /mi_ref_link - Obtener tu link de referido\n"
        "• /cambiar_tiktok - Cambiar tu usuario TikTok\n"
        "• Subir seguimiento, videos y lives desde el menú principal\n\n"
        "👑 Admin/Subadmin:\n"
        "• /listar_usuarios - Listar usuarios (coronas)\n"
        "• /dar_puntos <id> <cantidad> - Proponer dar puntos (subadmin) o ejecutar (admin)\n"
        "• /cambiar_tiktok_usuario <id> <@usuario> - Proponer/ejecutar cambio de TikTok\n"
        "• /crear_cupon <código4> <recompensa> <ganadores> - Crear/proponer cupón\n"
        "• /cobrar_cupon <código4> - Cobrar cupón\n"
        "• /add_subadmin <id> - Agregar subadmin (admin)\n"
        "• /remove_subadmin <id> - Quitar subadmin (admin)\n"
    )
    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(texto, reply_markup=back_to_menu_keyboard())
    else:
        await update_or_query.edit_message_text(texto, reply_markup=back_to_menu_keyboard())

# --- Comando: mi link de referido ---
async def cmd_my_ref_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_my_ref_link(update, context)

# --- Cupones ---
async def crear_cupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if len(args) != 3:
        await update.message.reply_text("Uso: /crear_cupon <código4> <recompensa> <ganadores>")
        return
    code = args[0].strip()
    if len(code) != 4 or not code.isdigit():
        await update.message.reply_text("⚠️ El código debe ser 4 dígitos.")
        return
    try:
        reward = float(args[1])
        winners = int(args[2])
    except:
        await update.message.reply_text("⚠️ Recompensa debe ser número (puntos) y ganadores un entero.")
        return

    if user_id == ADMIN_ID:
        async with async_session() as session:
            session.add(Coupon(code=code, reward=reward, winners_limit=winners, created_by=user_id))
            await session.commit()
        await update.message.reply_text(f"✅ Cupón creado: {code} (recompensa {reward}, ganadores {winners})")
    else:
        if not await is_subadmin(user_id):
            await update.message.reply_text("❌ No tienes permiso para proponer cupones.")
            return
        expires = datetime.utcnow() + timedelta(days=AUTO_APPROVE_AFTER_DAYS)
        async with async_session() as session:
            action = AdminAction(
                tipo="crear_cupon",
                target_id=0,
                cantidad=None,
                nuevo_alias=f"{code}|{reward}|{winners}",
                subadmin_id=user_id,
                status="pending",
                expires_at=expires,
                note=f"Propuesto por {user_id}"
            )
            session.add(action)
            await session.commit()
        await update.message.reply_text("🟡 Cupón propuesto. Pendiente de aprobación del admin.")
        await notify_admin(context, text=f"🟡 Propuesta de cupón: código {code}, recompensa {reward}, ganadores {winners} (por {user_id}).")

async def cobrar_cupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Uso: /cobrar_cupon <código4>")
        return
    code = args[0].strip()
    async with async_session() as session:
        res = await session.execute(select(Coupon).where(Coupon.code == code))
        coupon = res.scalars().first()
        if not coupon:
            await update.message.reply_text("❌ Cupón no encontrado.")
            return
        resc = await session.execute(select(func.count()).select_from(CouponClaim).where(CouponClaim.coupon_id == coupon.id))
        count = resc.scalar() or 0
        if count >= coupon.winners_limit:
            await update.message.reply_text("⚠️ Cupón agotado. Ya no hay ganadores disponibles.")
            return
        resu = await session.execute(select(CouponClaim).where(CouponClaim.coupon_id == coupon.id, CouponClaim.claimer_id == user_id))
        ya = resu.scalars().first()
        if ya:
            await update.message.reply_text("⚠️ Ya cobraste este cupón.")
            return
        res_actor = await session.execute(select(User).where(User.telegram_id == user_id))
        actor = res_actor.scalars().first()
        if actor:
            actor.balance = (actor.balance or 0) + coupon.reward
            session.add(Movimiento(telegram_id=user_id, detalle=f"Cobro cupón {code}", puntos=coupon.reward))
        session.add(CouponClaim(coupon_id=coupon.id, claimer_id=user_id))
        await session.commit()
    await update.message.reply_text(f"✅ Cupón cobrado: +{coupon.reward} puntos.")

# --- Main ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")

async def preflight():
    await init_db()
    await migrate_db()

loop = asyncio.get_event_loop()
loop.run_until_complete(preflight())

application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("inicio", start))
application.add_handler(CommandHandler("balance", cmd_balance))
application.add_handler(CommandHandler("listar_usuarios", listar_usuarios))
application.add_handler(CommandHandler("dar_puntos", dar_puntos))
application.add_handler(CommandHandler("cambiar_tiktok", cambiar_tiktok))
application.add_handler(CommandHandler("cambiar_tiktok_usuario", cambiar_tiktok_usuario))
application.add_handler(CommandHandler("add_subadmin", add_subadmin))
application.add_handler(CommandHandler("remove_subadmin", remove_subadmin))
application.add_handler(CommandHandler("mi_ref_link", cmd_my_ref_link))
application.add_handler(CommandHandler("comandos", comandos))
application.add_handler(CommandHandler("crear_cupon", crear_cupon))
application.add_handler(CommandHandler("cobrar_cupon", cobrar_cupon))
application.add_handler(CallbackQueryHandler(menu_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot activo y saludable!", 200

@flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "ok", 200

if __name__ == "__main__":
    loop.create_task(auto_approve_loop(application))
    loop.create_task(referral_weekly_summary_loop(application))
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        url_path=BOT_TOKEN,
        webhook_url=f"https://{RENDER_EXTERNAL_HOSTNAME}/{BOT_TOKEN}"
    )