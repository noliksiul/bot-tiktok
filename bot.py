# --- Módulo 1/7: Imports y Configuración ---
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions   # 👈 Controla las vistas previas
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
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

# 👇 Opcional: para scrapear títulos/miniaturas si quieres enriquecer previews
import aiohttp
from bs4 import BeautifulSoup

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
PUNTOS_REFERIDO_BONUS = 0.25
PUNTOS_LIVE_SOLO_VER = 0.5
PUNTOS_LIVE_QUIEREME_EXTRA = 1.5
LIVE_VIEW_MINUTES = 5

# --- Canal y grupo ---
CHANNEL_ID = -1003468913370
GROUP_URL = "https://t.me/+9sy0_CwwjnxlOTJh"
CHANNEL_URL = "https://t.me/apoyotiktok002"
CHANNEL_SHOP_ID = -1003664738296
CHANNEL_SHOP_URL = "https://t.me/ofertasimperdiblestiktokshop"

# --- Configuración administrador ---
ADMIN_ID = 890166032

# --- Módulo 2/7: Modelos y Base de Datos ---

# --- Tablas principales ---


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    tiktok_user = Column(Text)
    balance = Column(Float, default=10)
    referrer_id = Column(BigInteger, nullable=True, index=True)
    referral_code = Column(Text, unique=True, index=True)
    created_at = Column(TIMESTAMP, server_default=func.now())


class Movimiento(Base):
    __tablename__ = "movimientos"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True)
    detalle = Column(Text)
    puntos = Column(Float)
    created_at = Column(TIMESTAMP, server_default=func.now())


class Seguimiento(Base):
    __tablename__ = "seguimientos"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True)
    link = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())


class Interaccion(Base):
    __tablename__ = "interacciones"
    id = Column(Integer, primary_key=True)
    tipo = Column(Text)   # 'seguimiento' | 'live_view' | 'live_quiereme'
    item_id = Column(Integer)
    actor_id = Column(BigInteger)
    owner_id = Column(BigInteger)
    status = Column(Text, default="pending")
    puntos = Column(Float, default=0)
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
    tipo = Column(Text)   # 'dar_puntos' | 'cambiar_tiktok'
    target_id = Column(BigInteger)
    cantidad = Column(Integer, nullable=True)
    nuevo_alias = Column(Text, nullable=True)
    subadmin_id = Column(BigInteger)
    status = Column(Text, default="pending")
    created_at = Column(TIMESTAMP, server_default=func.now())
    expires_at = Column(TIMESTAMP)
    note = Column(Text, nullable=True)


class Live(Base):
    __tablename__ = "lives"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True)
    link = Column(Text)
    alias = Column(Text, nullable=True)
    puntos = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())
    expires_at = Column(TIMESTAMP)


class Coupon(Base):
    __tablename__ = "coupons"
    id = Column(Integer, primary_key=True)
    code = Column(Text, unique=True)
    total_points = Column(Integer)
    winners_limit = Column(Integer)
    created_by = Column(BigInteger)
    active = Column(Integer, default=1)
    created_at = Column(TIMESTAMP, server_default=func.now())

# --- Inicialización DB ---


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# --- Migración robusta ---


async def migrate_db():
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT;"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code TEXT;"))
        await conn.execute(text("ALTER TABLE users ALTER COLUMN balance TYPE FLOAT USING balance::float;"))
        await conn.execute(text("ALTER TABLE interacciones ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;"))
        await conn.execute(text("ALTER TABLE interacciones ALTER COLUMN puntos TYPE FLOAT USING puntos::float;"))
        await conn.execute(text("ALTER TABLE movimientos ALTER COLUMN puntos TYPE FLOAT USING puntos::float;"))
        await conn.execute(text("ALTER TABLE lives ADD COLUMN IF NOT EXISTS alias TEXT;"))
        await conn.execute(text("ALTER TABLE lives ADD COLUMN IF NOT EXISTS puntos INTEGER DEFAULT 0;"))
        await conn.execute(text("ALTER TABLE lives ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;"))

        # --- Módulo 3/7: Menú Principal y Start ---


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

# --- Menú principal ---


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

# --- Start con saludo personalizado y menú directo ---


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

    if not user.tiktok_user:
        await update.message.reply_text(
            "Por favor escribe tu usuario de TikTok (debe comenzar con @).\n"
            "Ejemplo: @lordnolik\n\n"
            "⚠️ Recuerda que si está mal tu usuario pueden rechazar el apoyo y no obtener los puntos."
        )
        context.user_data["state"] = "tiktok_user"
    else:
        await show_main_menu(update, context)
        # --- Módulo 4/7: Ver Contenido (con vistas previas) ---


async def show_contenido(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(update_or_query, Update):
        chat_id = update_or_query.effective_chat.id
        user_id = update_or_query.effective_user.id
        query = None
    else:
        query = update_or_query
        chat_id = query.message.chat.id
        user_id = query.from_user.id

    ultimo_tipo = context.user_data.get("ultimo_tipo", None)

    async with async_session() as session:
        # Orden de rotación: seguimiento → live
        if ultimo_tipo == "seguimiento":
            orden = ["live", "seguimiento"]
        elif ultimo_tipo == "live":
            orden = ["seguimiento", "live"]
        else:
            orden = ["seguimiento", "live"]

        for tipo in orden:
            # --- BLOQUE DE SEGUIMIENTO ---
            if tipo == "seguimiento":
                res_seg = await session.execute(
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
                seg = res_seg.scalars().first()
                if seg:
                    msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"👀 Seguimiento disponible:\n🗓️ {seg.created_at}\n{seg.link}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🌐 Abrir perfil", url=seg.link),
                             InlineKeyboardButton("➡️ Siguiente", callback_data="ver_contenido")],
                            [InlineKeyboardButton(
                                "🔙 Menú principal", callback_data="menu_principal")]
                        ]),
                        link_preview_options=LinkPreviewOptions(
                            is_disabled=False,
                            url=seg.link,
                            prefer_large_media=True,
                            show_above_text=True
                        )
                    )
                    old_job = context.user_data.get("contenido_job")
                    if old_job:
                        old_job.schedule_removal()
                    job = context.job_queue.run_once(
                        lambda _, sid=seg.id: context.bot.edit_message_reply_markup(
                            chat_id=chat_id,
                            message_id=msg.message_id,
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton(
                                    "🟡 Ya lo seguí ✅", callback_data=f"confirm_seguimiento_{sid}")],
                                [InlineKeyboardButton(
                                    "🔙 Menú principal", callback_data="menu_principal")]
                            ])
                        ),
                        when=20
                    )
                    context.user_data["contenido_job"] = job
                    context.user_data["ultimo_tipo"] = "seguimiento"
                    return

            # --- BLOQUE DE LIVE ---
            elif tipo == "live":
                res_live = await session.execute(
                    select(Live)
                    .where(Live.telegram_id != user_id)
                    .where(~Live.id.in_(
                        select(Interaccion.item_id).where(
                            Interaccion.actor_id == user_id,
                            Interaccion.tipo.in_(
                                ["live_view", "live_quiereme"])
                        )
                    ))
                    .where(Live.created_at >= datetime.utcnow() - timedelta(days=1))
                    .order_by(Live.created_at.desc())
                )
                live = res_live.scalars().first()
                if live:
                    msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🔴 Live disponible publicado por {live.alias or 'usuario'}\n\n"
                            f"⏳ Permanece al menos 2.5 minutos en el live\n{live.link}"
                        ),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                "👉🚀 Entrar aquí 🔴✨", callback_data=f"abrir_live_{live.id}")],
                            [InlineKeyboardButton(
                                "➡️ Siguiente", callback_data="ver_contenido")],
                            [InlineKeyboardButton(
                                "🔙 Menú principal", callback_data="menu_principal")]
                        ]),
                        link_preview_options=LinkPreviewOptions(
                            is_disabled=False,
                            url=live.link,
                            prefer_large_media=True,
                            show_above_text=True
                        )
                    )
                    old_job = context.user_data.get("contenido_job")
                    if old_job:
                        old_job.schedule_removal()
                    job = context.job_queue.run_once(
                        lambda _, lid=live.id: context.bot.edit_message_reply_markup(
                            chat_id=chat_id,
                            message_id=msg.message_id,
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton(
                                    "👀 Solo vi el live", callback_data=f"confirm_live_{lid}")],
                                [InlineKeyboardButton(
                                    "❤️ Vi el live y di Quiéreme", callback_data=f"live_quiereme_{lid}")],
                                [InlineKeyboardButton(
                                    "🔙 Menú principal", callback_data="menu_principal")]
                            ])
                        ),
                        when=150
                    )
                    context.user_data["contenido_job"] = job
                    context.user_data["ultimo_tipo"] = "live"
                    return

    # --- MENSAJE FINAL SI NO HAY CONTENIDO ---
    if query:
        await query.edit_message_text(
            text="⚠️ No hay contenido disponible por ahora.",
            reply_markup=back_to_menu_keyboard()
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ No hay contenido disponible por ahora.",
            reply_markup=back_to_menu_keyboard()
        )
        # --- Módulo 5/7: Handlers de Interacciones (continuación) ---

    # Cancelar cualquier job pendiente y reiniciar ciclo
    job = context.user_data.get("contenido_job")
    if job:
        job.schedule_removal()
        context.user_data["contenido_job"] = None
    context.user_data["ultimo_tipo"] = None

    # Confirmación al usuario
    await query.edit_message_text(
        f"✅ Tu apoyo al live fue registrado automáticamente. Ganaste {PUNTOS_LIVE_SOLO_VER} puntos.",
        reply_markup=back_to_menu_keyboard()
    )

# --- Registrar interacción de live con Quiéreme ---


async def handle_live_quiereme(query, context: ContextTypes.DEFAULT_TYPE, live_id: int):
    user_id = query.from_user.id
    async with async_session() as session:
        res_live = await session.execute(select(Live).where(Live.id == live_id))
        live = res_live.scalars().first()
        if not live:
            await query.edit_message_text("❌ Live no encontrado.", reply_markup=back_to_menu_keyboard())
            return
        if live.telegram_id == user_id:
            await query.answer("No puedes apoyar tu propio live.", show_alert=True)
            return

        # Verificar duplicados
        res_inter = await session.execute(
            select(Interaccion).where(
                Interaccion.tipo == "live_quiereme",
                Interaccion.item_id == live.id,
                Interaccion.actor_id == user_id
            )
        )
        inter = res_inter.scalars().first()

        if inter:
            if inter.status == "pending":
                await query.answer("⚠️ Ya habías registrado tu apoyo, está pendiente de aprobación.", show_alert=True)
            else:
                await query.answer(f"⚠️ Esta interacción ya está en estado: {inter.status}.", show_alert=True)
            return
        else:
            # Crear nueva interacción con puntos extra
            expires = datetime.utcnow() + timedelta(days=2)
            inter = Interaccion(
                tipo="live_quiereme",
                item_id=live.id,
                actor_id=user_id,
                owner_id=live.telegram_id,
                status="pending",
                puntos=PUNTOS_LIVE_QUIEREME_EXTRA,
                expires_at=expires
            )
            session.add(inter)
            await session.commit()

        # Obtener TikTok del actor
        res_actor = await session.execute(select(User).where(User.telegram_id == user_id))
        actor = res_actor.scalars().first()

    # Cancelar cualquier job pendiente y reiniciar ciclo
    job = context.user_data.get("contenido_job")
    if job:
        job.schedule_removal()
        context.user_data["contenido_job"] = None
    context.user_data["ultimo_tipo"] = None

    # Confirmación al usuario
    await query.edit_message_text(
        "🟡 Tu apoyo con Quiéreme fue registrado y está pendiente de aprobación del dueño.",
        reply_markup=back_to_menu_keyboard()
    )

    # Notificar al dueño
    await notify_user(
        context,
        chat_id=live.telegram_id,
        text=(
            f"📩 Nuevo apoyo a tu live con Quiéreme:\n"
            f"Item ID: {live.id}\n"
            f"Actor: {user_id}\n"
            f"Usuario TikTok: {actor.tiktok_user or 'no registrado'}\n"
            f"Puntos: {PUNTOS_LIVE_QUIEREME_EXTRA}\n\n"
            "¿Apruebas?"
        ),
        reply_markup=yes_no_keyboard(
            callback_yes=f"approve_interaction_{inter.id}",
            callback_no=f"reject_interaction_{inter.id}"
        )
    )
    # --- Módulo 6/7: Comandos y Administración ---

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

# --- Gestión de SubAdmins ---


async def add_subadmin(update: Update, context: ContextTypes.DEFAULT_TYPE): ...
async def remove_subadmin(
    update: Update, context: ContextTypes.DEFAULT_TYPE): ...

# --- Dar puntos ---


async def dar_puntos(update: Update, context: ContextTypes.DEFAULT_TYPE): ...

# --- Listar usuarios ---


async def listar_usuarios(
    update: Update, context: ContextTypes.DEFAULT_TYPE): ...

# --- Referidos ---


async def show_my_ref_link(
    update_or_query, context: ContextTypes.DEFAULT_TYPE): ...


async def referral_weekly_summary(
    update_or_query, context: ContextTypes.DEFAULT_TYPE): ...

# --- Cupones ---


async def subir_cupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No tienes permiso para usar este comando.")
        return
    args = context.args
    if len(args) != 3:
        await update.message.reply_text("Uso: /subir_cupon <codigo> <puntos_totales> <limite_ganadores>")
        return
    code = args[0]
    try:
        total_points = int(args[1])
        winners_limit = int(args[2])
    except:
        await update.message.reply_text("⚠️ Argumentos inválidos.")
        return
    async with async_session() as session:
        res = await session.execute(select(Coupon).where(Coupon.code == code))
        exists = res.scalars().first()
        if exists:
            await update.message.reply_text("⚠️ Ya existe un cupón con ese código.")
            return
        coupon = Coupon(code=code, total_points=total_points,
                        winners_limit=winners_limit, created_by=update.effective_user.id)
        session.add(coupon)
        await session.commit()
    await update.message.reply_text(f"✅ Cupón creado: {code} con {total_points} puntos y {winners_limit} ganadores.")


async def cobrar_cupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Uso: /cobrar_cupon <codigo>")
        return
    code = args[0]
    user_id = update.effective_user.id
    async with async_session() as session:
        res = await session.execute(select(Coupon).where(Coupon.code == code))
        coupon = res.scalars().first()
        if not coupon or coupon.active != 1:
            await update.message.reply_text("❌ Cupón inválido o inactivo.")
            return
        # Verificar ganadores previos
        res_mov = await session.execute(
            select(Movimiento).where(Movimiento.detalle.like(f"Cupón {code}%"))
        )
        ganadores = res_mov.scalars().all()
        if len(ganadores) >= coupon.winners_limit:
            await update.message.reply_text("⚠️ Este cupón ya alcanzó el límite de ganadores.")
            return
        # Verificar si ya lo cobró
        for g in ganadores:
            if g.telegram_id == user_id:
                await update.message.reply_text("⚠️ Ya cobraste este cupón.")
                return
        # Acreditar puntos
        res_user = await session.execute(select(User).where(User.telegram_id == user_id))
        user = res_user.scalars().first()
        if not user:
            await update.message.reply_text("❌ Usuario no registrado.")
            return
        user.balance = (user.balance or 0) + coupon.total_points
        mov = Movimiento(telegram_id=user_id,
                         detalle=f"Cupón {code}", puntos=coupon.total_points)
        session.add(mov)
        await session.commit()
    await update.message.reply_text(f"✅ Cupón {code} cobrado. Ganaste {coupon.total_points} puntos.")

# --- Comandos ---


async def comandos(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "📋 Lista de comandos disponibles:\n\n"
        "/start - Iniciar y registrarse\n"
        "/balance - Ver tu balance e historial\n"
        "/mi_ref_link - Obtener tu link de referido\n"
        "/resumen_referidos - Ver resumen semanal de referidos\n"
        "/subir_cupon - Crear un cupón (admin)\n"
        "/cobrar_cupon <codigo> - Cobrar un cupón\n"
        "/add_subadmin <id> - Agregar subadmin (admin)\n"
        "/remove_subadmin <id> - Eliminar subadmin (admin)\n"
        "/dar_puntos <id> <cantidad> - Dar puntos (admin)\n"
        "/listar_usuarios - Listar usuarios (admin)\n"
    )
    reply_markup = back_to_menu_keyboard()
    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(texto, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(texto, reply_markup=reply_markup)

        # --- Módulo 7/7: Main y Render ---

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")

# --- Inicialización DB ---


async def preflight():
    await init_db()
    await migrate_db()

loop = asyncio.get_event_loop()
loop.run_until_complete(preflight())

# --- Notificación genérica ---


async def notify_user(context, chat_id: int, text: str, reply_markup=None):
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        print(f"Error notificando a {chat_id}: {e}")

# --- Auto-aprobación de interacciones expiradas ---


async def auto_approve_loop(app: Application):
    async with async_session() as session:
        now = datetime.utcnow()
        res = await session.execute(
            select(Interaccion).where(Interaccion.status ==
                                      "pending").where(Interaccion.expires_at < now)
        )
        interacciones = res.scalars().all()
        for inter in interacciones:
            inter.status = "accepted"
            res_actor = await session.execute(select(User).where(User.telegram_id == inter.actor_id))
            actor = res_actor.scalars().first()
            if actor:
                actor.balance = (actor.balance or 0) + (inter.puntos or 0)
                mov = Movimiento(
                    telegram_id=inter.actor_id,
                    detalle=f"Auto-aprobado {inter.tipo}",
                    puntos=inter.puntos
                )
                session.add(mov)
        await session.commit()

# --- Flask para Render ---
flask_app = Flask(__name__)


@flask_app.route("/")
def index():
    return "Bot activo en Render"

# --- Handler para texto (registro de usuario TikTok) ---


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if state == "tiktok_user":
        username = update.message.text.strip()
        if not username.startswith("@"):
            await update.message.reply_text("⚠️ El usuario de TikTok debe comenzar con @. Intenta de nuevo.")
            return
        async with async_session() as session:
            res = await session.execute(select(User).where(User.telegram_id == update.effective_user.id))
            user = res.scalars().first()
            if user:
                user.tiktok_user = username
                await session.commit()
        context.user_data["state"] = None
        await update.message.reply_text(f"✅ Usuario TikTok registrado: {username}")
        await show_main_menu(update, context)

# --- Main con Webhook ---


async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers principales
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", cmd_balance))
    application.add_handler(CommandHandler("add_subadmin", add_subadmin))
    application.add_handler(CommandHandler("remove_subadmin", remove_subadmin))
    application.add_handler(CommandHandler("dar_puntos", dar_puntos))
    application.add_handler(CommandHandler("listar_usuarios", listar_usuarios))
    application.add_handler(CommandHandler("subir_cupon", subir_cupon))
    application.add_handler(CommandHandler("cobrar_cupon", cobrar_cupon))
    application.add_handler(CommandHandler("comandos", comandos))

    # Callbacks de menú
    application.add_handler(CallbackQueryHandler(
        lambda u, c: show_main_menu(u, c), pattern="menu_principal"))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: show_contenido(u, c), pattern="ver_contenido"))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: show_balance(u, c), pattern="balance"))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: show_my_ref_link(u, c), pattern="mi_ref_link"))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: referral_weekly_summary(u, c), pattern="resumen_referidos"))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: comandos(u, c), pattern="comandos"))

    # Callbacks de interacciones
    application.add_handler(CallbackQueryHandler(
        lambda q, c: handle_seguimiento_done(q, c, int(q.data.split("_")[-1])),
        pattern="confirm_seguimiento_"
    ))
    application.add_handler(CallbackQueryHandler(
        lambda q, c: handle_live_view(q, c, int(q.data.split("_")[-1])),
        pattern="confirm_live_"
    ))
    application.add_handler(CallbackQueryHandler(
        lambda q, c: handle_live_quiereme(q, c, int(q.data.split("_")[-1])),
        pattern="live_quiereme_"
    ))
    application.add_handler(CallbackQueryHandler(
        lambda q, c: approve_interaction(q, c, int(q.data.split("_")[-1])),
        pattern="approve_interaction_"
    ))
    application.add_handler(CallbackQueryHandler(
        lambda q, c: reject_interaction(q, c, int(q.data.split("_")[-1])),
        pattern="reject_interaction_"
    ))

    # Mensajes de texto para registrar usuario TikTok
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_text))

    # Job de auto-aprobación cada hora
    application.job_queue.run_repeating(
        lambda _: auto_approve_loop(application), interval=3600, first=10)

    # Configurar webhook con await
    port = int(os.environ.get("PORT", 5000))
    webhook_url = f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
    await application.bot.set_webhook(url=webhook_url)

    # Endpoint Flask para recibir updates
    @flask_app.route("/webhook", methods=["POST"])
    def webhook():
        update = Update.de_json(request.get_json(force=True), application.bot)
        application.update_queue.put_nowait(update)
        return "ok", 200

    # Levantar Flask
    flask_app.run(host="0.0.0.0", port=port)

# --- Ejecución ---
if __name__ == "__main__":
    asyncio.run(main())
