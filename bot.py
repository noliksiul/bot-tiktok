# bot.py (Parte 1/5)

import os
import asyncio
import secrets
from datetime import datetime, timedelta

from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from sqlalchemy import (
    Column, Integer, BigInteger, Text, TIMESTAMP, func,
    UniqueConstraint, select, text
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

# --- Config puntos ---
PUNTOS_APOYO_SEGUIMIENTO = 2
PUNTOS_APOYO_VIDEO = 3
PUNTOS_REFERIDO_BONUS = 0.25

# --- Canal y grupo ---
CHANNEL_ID = -1003468913370
GROUP_URL = "https://t.me/+9sy0_CwwjnxlOTJh"
CHANNEL_URL = "https://t.me/apoyotiktok002"

# --- Configuración administrador ---
ADMIN_ID = 890166032

# --- Utilidades UI ---
def back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]]
    )

def yes_no_keyboard(callback_yes: str, callback_no: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Aprobar", callback_data=callback_yes),
         InlineKeyboardButton("❌ Rechazar", callback_data=callback_no)],
        [InlineKeyboardButton("🔙 Menú", callback_data="menu_principal")]
    ])

# --- Tablas ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    tiktok_user = Column(Text)
    balance = Column(Integer, default=10)
    referrer_id = Column(BigInteger, nullable=True, index=True)
    referral_code = Column(Text, unique=True, index=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

class Movimiento(Base):
    __tablename__ = "movimientos"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True)
    detalle = Column(Text)
    puntos = Column(Integer)
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
    status = Column(Text, default="pending")  # pending | accepted | rejected | auto_accepted
    puntos = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())
    expires_at = Column(TIMESTAMP)  # fecha límite para auto-aprobar
    __table_args__ = (UniqueConstraint("tipo", "item_id", "actor_id", name="uniq_tipo_item_actor"),)

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
    status = Column(Text, default="pending")  # pending | accepted | rejected | auto_accepted
    created_at = Column(TIMESTAMP, server_default=func.now())
    expires_at = Column(TIMESTAMP)  # fecha límite para auto-aprobar
    note = Column(Text, nullable=True)

# --- Inicialización DB ---
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# --- Migración robusta: añadir columnas e índices faltantes ---
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

        # interacciones: expires_at + índice
        await conn.execute(text("ALTER TABLE interacciones ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_interacciones_status_expires ON interacciones(status, expires_at);"))

        # admin_actions: expires_at + índice
        await conn.execute(text("ALTER TABLE admin_actions ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_admin_actions_status_expires ON admin_actions(status, expires_at);"))

        # movimientos: índice por usuario
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_movimientos_telegram_id ON movimientos(telegram_id);"))

        # Seguimiento/Video: índices por dueño
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_seguimientos_telegram_id ON seguimientos(telegram_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_videos_telegram_id ON videos(telegram_id);"))

# --- Helpers de referidos ---
def build_referral_deeplink(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start=ref_{code}"

async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    me = await context.bot.get_me()
    return me.username

# --- Notificaciones seguras ---
async def notify_admin(context: ContextTypes.DEFAULT_TYPE, text: str):
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=text)
    except Exception as e:
        print("Aviso: no se pudo notificar al admin:", e)

async def notify_user(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, reply_markup=None):
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        print("Aviso: no se pudo notificar al usuario:", e)

# --- Tarea periódica: auto-acreditación ---
AUTO_APPROVE_INTERVAL_SECONDS = 60
AUTO_APPROVE_AFTER_DAYS = 2

async def auto_approve_loop(application: Application):
    await asyncio.sleep(5)
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
                    res_actor = await session.execute(select(User).where(User.telegram_id == inter.actor_id))
                    actor = res_actor.scalars().first()
                    if actor:
                        actor.balance = (actor.balance or 0) + (inter.puntos or 0)
                        session.add(Movimiento(
                            telegram_id=inter.actor_id,
                            detalle=f"Auto-aprobado {inter.tipo}",
                            puntos=inter.puntos
                        ))
                        # bonus referrer
                        if actor.referrer_id:
                            res_ref = await session.execute(select(User).where(User.telegram_id == actor.referrer_id))
                            referrer = res_ref.scalars().first()
                            if referrer:
                                referrer.balance = (referrer.balance or 0) + PUNTOS_REFERIDO_BONUS
                                session.add(Movimiento(
                                    telegram_id=referrer.telegram_id,
                                    detalle="Bonus por referido (auto-aprobado)",
                                    puntos=PUNTOS_REFERIDO_BONUS
                                ))
                                try:
                                    await application.bot.send_message(
                                        chat_id=referrer.telegram_id,
                                        text=f"💸 Bonus automático: {PUNTOS_REFERIDO_BONUS} puntos por interacción auto-aprobada de tu referido {actor.telegram_id}."
                                    )
                                except Exception as e:
                                    print("Aviso: no se pudo notificar bonus auto:", e)
                await session.commit()
        except Exception as e:
            print("Error en auto_approve_loop:", e)
        await asyncio.sleep(AUTO_APPROVE_INTERVAL_SECONDS)

# --- Resumen semanal de referidos ---
async def referral_weekly_summary_loop(application: Application):
    await asyncio.sleep(10)
    while True:
        try:
            async with async_session() as session:
                # Sumatoria de bonus por referido en últimos 7 días
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
                                text=f"📊 Resumen semanal: ganaste {total} puntos por referidos en los últimos 7 días."
                            )
                        except Exception as e:
                            print("Aviso: no se pudo enviar resumen semanal:", e)
        except Exception as e:
            print("Error en referral_weekly_summary_loop:", e)
        await asyncio.sleep(3600 * 24 * 7)  # cada semana
# bot.py (Parte 2/5)

# --- Menú principal ---
async def show_main_menu(update_or_query, context, message="🏠 Menú principal:"):
    keyboard = [
        [InlineKeyboardButton("📈 Subir seguimiento", callback_data="subir_seguimiento")],
        [InlineKeyboardButton("🎥 Subir video", callback_data="subir_video")],
        [InlineKeyboardButton("👀 Ver seguimiento", callback_data="ver_seguimiento")],
        [InlineKeyboardButton("📺 Ver video", callback_data="ver_video")],
        [InlineKeyboardButton("💰 Balance e historial", callback_data="balance")],
        [InlineKeyboardButton("🔗 Mi link de referido", callback_data="mi_ref_link")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if isinstance(update_or_query, Update) and getattr(update_or_query, "message", None):
        await update_or_query.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(message, reply_markup=reply_markup)

# --- Start con referidos y notificaciones al referrer ---
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
            # fallback: migrar y reintentar
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

            # notificación al referrer: nuevo referido
            if user.referrer_id:
                await notify_user(
                    context,
                    chat_id=user.referrer_id,
                    text=f"🎉 Nuevo referido: {update.effective_user.id} (@{update.effective_user.username or 'sin_username'}) se registró con tu link."
                )

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
            "⚠️ Tu usuario de TikTok debe comenzar con @. Ejemplo: @rosjimcaro",
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
        "🔄 Envía tu nuevo usuario de TikTok (debe comenzar con @).",
        reply_markup=back_to_menu_keyboard()
    )
    context.user_data["state"] = "cambiar_tiktok"

async def save_new_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text.strip()
    if not tiktok_user.startswith("@"):
        await update.message.reply_text(
            "⚠️ Tu usuario de TikTok debe comenzar con @. Ejemplo: @rosjimcaro",
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

    await update.message.reply_text("✅ Tu seguimiento se subió con éxito.", reply_markup=back_to_menu_keyboard())
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

    await update.message.reply_text("✅ Tu video se subió con éxito.", reply_markup=back_to_menu_keyboard())
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
        f"🗓️ {vid.created_at}\n\nPulsa el botón si ya apoyaste."
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

    await query.edit_message_text("🟡 Tu apoyo fue registrado y está pendiente de aprobación del dueño.", reply_markup=back_to_menu_keyboard())
    await notify_user(
        context,
        chat_id=seg.telegram_id,
        text=f"📩 Nuevo apoyo a tu seguimiento:\nItem ID: {seg.id}\nActor: {user_id}\nPuntos: {PUNTOS_APOYO_SEGUIMIENTO}\n\n¿Apruebas?",
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

    await query.edit_message_text("🟡 Tu apoyo fue registrado y está pendiente de aprobación del dueño.", reply_markup=back_to_menu_keyboard())
    await notify_user(
        context,
        chat_id=vid.telegram_id,
        text=f"📩 Nuevo apoyo a tu video:\nItem ID: {vid.id}\nActor: {user_id}\nPuntos: {PUNTOS_APOYO_VIDEO}\n\n¿Apruebas?",
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
        res = await session.execute(select(User).where(User.telegram_id == inter.actor_id))
        actor = res.scalars().first()
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

# --- Listar usuarios (solo admin) ---
async def listar_usuarios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No tienes permiso para usar este comando.")
        return

    async with async_session() as session:
        res = await session.execute(select(User))
        usuarios = res.scalars().all()

    if not usuarios:
        await update.message.reply_text("⚠️ No hay usuarios registrados.")
        return

    texto = "👥 Usuarios registrados:\n"
    for u in usuarios:
        texto += f"- ID: {u.telegram_id}, TikTok: {u.tiktok_user}, Balance: {u.balance}, Referrer: {u.referrer_id}\n"

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
    # subadmin propone dar puntos a un usuario; admin aprueba
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
        cantidad = int(args[1])
    except:
        await update.message.reply_text("⚠️ Ambos parámetros deben ser números.")
        return

    expires = datetime.utcnow() + timedelta(days=AUTO_APPROVE_AFTER_DAYS)
    async with async_session() as session:
        action = AdminAction(
            tipo="dar_puntos",
            target_id=target_id,
            cantidad=cantidad,
            subadmin_id=user_id,
            status="pending",
            expires_at=expires,
            note=f"Propuesto por {user_id}"
        )
        session.add(action)
        await session.commit()

    await update.message.reply_text(f"🟡 Acción propuesta: dar {cantidad} puntos a {target_id}. Queda pendiente de aprobación del admin.")
    # notificar admin
    await notify_admin(
        context,
        text=f"🟡 Acción pendiente: dar {cantidad} puntos a {target_id} (propuesta por {user_id}).",
    )

async def cambiar_tiktok_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # subadmin propone cambiar el alias TikTok de un usuario; admin aprueba
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
    await notify_admin(
        context,
        text=f"🟡 Acción pendiente: cambiar TikTok de {target_id} a {nuevo_alias} (propuesta por {user_id}).",
    )

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

    elif data == "ver_seguimiento":
        await show_seguimientos(query, context)

    elif data == "ver_video":
        await show_videos(query, context)

    elif data == "balance":
        await show_balance(query, context)

    elif data == "mi_ref_link":
        await show_my_ref_link(query, context)

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
    else:
        await update.message.reply_text(
            "⚠️ Usa el menú para interactuar con el bot.\n\nSi es tu primera vez, escribe /start.",
            reply_markup=back_to_menu_keyboard()
        )

# --- Comando: mi link de referido ---
async def cmd_my_ref_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_my_ref_link(update, context)

# --- Main ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")

# Ejecuta migraciones ANTES de construir la app y handlers
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
application.add_handler(CallbackQueryHandler(menu_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

flask_app = Flask(__name__)

# --- Endpoint raíz para UptimeRobot ---
@flask_app.route("/")
def home():
    return "Bot activo y saludable!", 200

# --- Webhook de Telegram ---
@flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "ok", 200

# --- Run ---
if __name__ == "__main__":
    # lanzar tareas periódicas
    loop.create_task(auto_approve_loop(application))
    loop.create_task(referral_weekly_summary_loop(application))
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        url_path=BOT_TOKEN,
        webhook_url=f"https://{RENDER_EXTERNAL_HOSTNAME}/{BOT_TOKEN}"
    )