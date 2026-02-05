# bot.py (Parte 1/5)l

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
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
    UniqueConstraint, select, text, Float   # 👈 AGREGA Float
)


from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

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

# --- Configuración administrador ---
ADMIN_ID = 890166032
auto_ref_counter = 0


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

# --- Tablas ---


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    # 👈 CAMBIO: ahora es único
    tiktok_user = Column(Text, unique=True, index=True)
    balance = Column(Float, default=10)
    referrer_id = Column(BigInteger, nullable=True, index=True)
    referral_code = Column(Text, unique=True, index=True)
    created_at = Column(TIMESTAMP, server_default=func.now())


class Movimiento(Base):
    __tablename__ = "movimientos"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, index=True)
    detalle = Column(Text)
    puntos = Column(Float)   # ✅ CAMBIAR a Float
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
    puntos = Column(Float, default=0)   # 👈 CAMBIAR a Float
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
    alias = Column(Text, nullable=True)   # 👈 nuevo campo
    puntos = Column(Integer, default=0)   # 👈 nuevo campo
    created_at = Column(TIMESTAMP, server_default=func.now())

# --- Modelos de cupones ---


class Cupon(Base):
    __tablename__ = "cupones"
    id = Column(Integer, primary_key=True)
    codigo = Column(Text, unique=True, index=True)
    puntos = Column(Float)
    ganadores = Column(Integer)
    usados = Column(Integer, default=0)
    creado_por = Column(BigInteger)
    created_at = Column(TIMESTAMP, server_default=func.now())


class CuponClaim(Base):
    __tablename__ = "cupon_claims"
    id = Column(Integer, primary_key=True)
    codigo = Column(Text, index=True)
    telegram_id = Column(BigInteger, index=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    # UNIQUE(codigo, telegram_id) está en la migración

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
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tiktok_user ON users(tiktok_user);"))
        # users: convertir balance a FLOAT
        await conn.execute(text("ALTER TABLE users ALTER COLUMN balance TYPE FLOAT USING balance::float;"))

        # interacciones: expires_at + índice
        await conn.execute(text("ALTER TABLE interacciones ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_interacciones_status_expires ON interacciones(status, expires_at);"))

        # interacciones: convertir puntos a FLOAT
        await conn.execute(text("ALTER TABLE interacciones ALTER COLUMN puntos TYPE FLOAT USING puntos::float;"))

        # cupones: tabla principal
        await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cupones (
            id SERIAL PRIMARY KEY,
            codigo TEXT UNIQUE,
            puntos FLOAT,
            ganadores INTEGER,
            usados INTEGER DEFAULT 0,
            creado_por BIGINT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cupones_codigo ON cupones(codigo);"))

        # cupon_claims: quién cobró qué cupón (evita doble cobro)
        await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cupon_claims (
            id SERIAL PRIMARY KEY,
            codigo TEXT,
            telegram_id BIGINT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE (codigo, telegram_id)
        );
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cupon_claims_codigo ON cupon_claims(codigo);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cupon_claims_user ON cupon_claims(telegram_id);"))

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
        await conn.execute(text("ALTER TABLE lives ADD COLUMN IF NOT EXISTS puntos FLOAT DEFAULT 0;"))
# --- Helpers de referidos ---


def build_referral_deeplink(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start=ref_{code}"


async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    me = await context.bot.get_me()
    return me.username

# --- Notificaciones seguras ---


async def notify_user(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, reply_markup=None):
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        print("Aviso: no se pudo notificar al usuario:", e)

# --- Cupones: subir cupón (admin/subadmin) ---


async def subir_cupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # Solo admin o subadmin pueden crear
    if uid != ADMIN_ID and not await is_subadmin(uid):
        await update.message.reply_text("❌ No tienes permiso para crear cupones.")
        return

    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Uso: /subir_cupon <puntos> <ganadores> <codigo>")
        return

    try:
        puntos = float(args[0])
        ganadores = int(args[1])
        codigo = args[2].strip()
    except Exception:
        await update.message.reply_text("⚠️ Parámetros inválidos.")
        return

    async with async_session() as session:
        # Verificar si ya existe
        res = await session.execute(select(Cupon).where(Cupon.codigo == codigo))
        existe = res.scalars().first()
        if existe:
            await update.message.reply_text("⚠️ Ese código ya existe.")
            return

        cupon = Cupon(codigo=codigo, puntos=puntos,
                      ganadores=ganadores, creado_por=uid)
        session.add(cupon)
        await session.commit()

    await update.message.reply_text(
        f"✅ Se subió cupón con éxito\n• Código: {codigo}\n• Puntos: {puntos:.2f}\n• Ganadores: {ganadores}"
    )


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
                                        text=f"💸 Bonus automático: {PUNTOS_REFERIDO_BONUS} puntos por interacción auto-aprobada de tu referido {actor.telegram_id}."
                                    )
                                except Exception as e:
                                    print(
                                        "Aviso: no se pudo notificar bonus auto:", e)
                await session.commit()
        except Exception as e:
            print("Error en auto_approve_loop:", e)
        await asyncio.sleep(AUTO_APPROVE_INTERVAL_SECONDS)

# --- Resumen semanal de referidos ---


async def referral_weekly_summary(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    user_id = update_or_query.effective_user.id if isinstance(
        update_or_query, Update) else update_or_query.from_user.id

    async with async_session() as session:
        since = datetime.utcnow() - timedelta(days=7)
        res = await session.execute(
            select(Movimiento.telegram_id, func.sum(Movimiento.puntos))
            .where(Movimiento.detalle.like("%Bonus por referido%"))
            .where(Movimiento.created_at >= since)
            .group_by(Movimiento.telegram_id)
        )
        rows = res.all()

    if not rows:
        texto = "⚠️ No hay puntos por referidos en los últimos 7 días."
    else:
        texto = "📊 Resumen semanal de referidos:\n"
        for chat_id, total in rows:
            if total and total > 0 and chat_id == user_id:
                texto += f"- Ganaste {total:.2f} puntos por referidos.\n"

    reply_markup = back_to_menu_keyboard()
    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(texto, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(texto, reply_markup=reply_markup)

# bot.py (Parte 2/5)

# --- Menú principal ---


async def show_main_menu(update_or_query, context, message="🏠 Menú principal:"):
    keyboard = [
        [InlineKeyboardButton("📈 Subir seguimiento",
                              callback_data="subir_seguimiento")],
        [InlineKeyboardButton("🎥 Subir video", callback_data="subir_video")],
        [InlineKeyboardButton("📡 Subir live", callback_data="subir_live")],
        [InlineKeyboardButton("📺 Ver video", callback_data="ver_video")],
        [InlineKeyboardButton("👀 Ver seguimiento",
                              callback_data="ver_seguimiento")],
        [InlineKeyboardButton("🔴 Ver live en vivo", callback_data="ver_live")],
        [InlineKeyboardButton("💰 Balance e historial",
                              callback_data="balance")],
        [InlineKeyboardButton("🔗 Mi link de referido",
                              callback_data="mi_ref_link")],
        [InlineKeyboardButton("📋 Comandos", callback_data="comandos")],
        [InlineKeyboardButton("🧾 Subir cupón", callback_data="subir_cupon")],
        [InlineKeyboardButton("💳 Cobrar cupón", callback_data="cobrar_cupon")],
        [InlineKeyboardButton("📊 Resumen semanal referidos",
                              callback_data="resumen_referidos")],
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
                # si viene con código de referido
                res_ref = await session.execute(select(User).where(User.referral_code == ref_code))
                referrer = res_ref.scalars().first()
                if referrer and referrer.telegram_id != update.effective_user.id:
                    user.referrer_id = referrer.telegram_id
            else:
                # ✅ Asignación automática si NO trae ref_code
                # Reparto 3:1 entre ADMIN y subadmin

                global auto_ref_counter
                try:
                    auto_ref_counter += 1
                except NameError:
                    auto_ref_counter = 1

                if auto_ref_counter % 4 == 0:
                    # Cada 4º usuario → subadmin
                    res_sa = await session.execute(select(SubAdmin).order_by(SubAdmin.id.asc()))
                    sa = res_sa.scalars().first()
                    if sa:
                        user.referrer_id = sa.telegram_id
                    else:
                        user.referrer_id = ADMIN_ID   # fallback si no hay subadmin
                else:
                    # Los otros 3 → dueño
                    user.referrer_id = ADMIN_ID

            session.add(user)
            await session.commit()

            if user.referrer_id:
                await notify_user(
                    context,
                    chat_id=user.referrer_id,
                    text=f"🎉 Nuevo referido: {update.effective_user.id} (@{update.effective_user.username or 'sin_username'}) se registró con tu link."
                )
    # Bienvenida sin saldo y sin botón extra
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
        # link del canal de ofertas
        [InlineKeyboardButton("🛍️ Ir al canal ofertas",
                              url="https://t.me/ofertasimperdiblestiktokshop")]
    ])
    await update.message.reply_text(
        "📢 Recuerda seguir nuestros canales para no perderte amistades, promociones y códigos para el bot.",
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
            try:
                await session.commit()
            except Exception:
                await update.message.reply_text(
                    "⚠️ Ese usuario de TikTok ya está registrado por otra persona.",
                    reply_markup=back_to_menu_keyboard()
                )
                return

    await update.message.reply_text(
        f"✅ Usuario TikTok registrado: {tiktok_user}",
        reply_markup=back_to_menu_keyboard()
    )
    context.user_data["state"] = None
    await show_main_menu(update, context)


# --- Cupones: cobrar cupón (usuarios)# --- Guardar usuario TikTok ---

async def cobrar_cupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Uso: /cobrar_cupon <codigo>
    if update.message is None:
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Uso: /cobrar_cupon <codigo>", reply_markup=back_to_menu_keyboard())
        return

    codigo = args[0].strip()
    uid = update.effective_user.id

    async with async_session() as session:
        res = await session.execute(select(Cupon).where(Cupon.codigo == codigo))
        cupon = res.scalars().first()
        if not cupon:
            await update.message.reply_text("❌ Cupón no encontrado.", reply_markup=back_to_menu_keyboard())
            return

        if cupon.usados >= cupon.ganadores:
            await update.message.reply_text("⚠️ Cupón agotado.", reply_markup=back_to_menu_keyboard())
            return

        res_claim = await session.execute(select(CuponClaim).where(CuponClaim.codigo == codigo, CuponClaim.telegram_id == uid))
        ya_cobrado = res_claim.scalars().first()
        if ya_cobrado:
            await update.message.reply_text("⚠️ Ya cobraste este cupón.", reply_markup=back_to_menu_keyboard())
            return

        res_u = await session.execute(select(User).where(User.telegram_id == uid))
        user = res_u.scalars().first()
        if not user:
            await update.message.reply_text("❌ No estás registrado. Usa /start primero.", reply_markup=back_to_menu_keyboard())
            return

        user.balance = (user.balance or 0) + (cupon.puntos or 0)
        session.add(Movimiento(telegram_id=uid,
                    detalle=f"Cobro cupón {codigo}", puntos=cupon.puntos))
        cupon.usados += 1
        session.add(CuponClaim(codigo=codigo, telegram_id=uid))
        await session.commit()

    await update.message.reply_text(
        f"✅ Se cobró cupón con éxito\n• Código: {codigo}\n• Puntos sumados: {cupon.puntos:.2f}",
        reply_markup=back_to_menu_keyboard()
    )


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
            try:
                await session.commit()
            except Exception:
                await update.message.reply_text(
                    "⚠️ Ese usuario de TikTok ya está registrado por otra persona.",
                    reply_markup=back_to_menu_keyboard()
                )
                return

    await update.message.reply_text(
        f"✅ Usuario TikTok actualizado: {tiktok_user}",
        reply_markup=back_to_menu_keyboard()
    )
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
        mov = Movimiento(telegram_id=user_id,
                         detalle="Subir seguimiento", puntos=-3)
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

# --- Subir live ---


async def save_live_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    link = update.message.text.strip()

    async with async_session() as session:
        # Validar usuario
        res = await session.execute(select(User).where(User.telegram_id == user_id))
        u = res.scalars().first()
        if not u:
            await update.message.reply_text("⚠️ No estás registrado en el sistema.", reply_markup=back_to_menu_keyboard())
            return

        # Cobro: subir live cuesta 3 puntos
        if (u.balance or 0) < 3:
            await update.message.reply_text("⚠️ No tienes suficientes puntos para subir un live (mínimo 3).", reply_markup=back_to_menu_keyboard())
            return

        # Guardar el live
        live = Live(
            telegram_id=user_id,
            link=link,
            alias=u.tiktok_user,
            puntos=0
        )
        session.add(live)

        # Registrar costo y movimiento
        u.balance = (u.balance or 0) - 3
        session.add(Movimiento(telegram_id=user_id,
                    detalle="Subir live", puntos=-3))

        await session.commit()

    # ✅ Publicar en el canal con botones
    try:
        alias = u.tiktok_user or (
            f"@{update.effective_user.username}" if update.effective_user.username else str(user_id))
        canal_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Ver live en vivo",
                                  callback_data="ver_live")],
            [InlineKeyboardButton(
                "🔙 Regresar al menú principal", callback_data="menu_principal")]
        ])
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🔴 Nuevo live publicado por {alias}\n\n{link}\n\n¡Apóyalo para ganar puntos!",
            reply_markup=canal_markup
        )
    except Exception as e:
        print("No se pudo publicar en el canal:", e)

    # ✅ Notificar a todos los usuarios (excepto el que subió) con botones
    async with async_session() as session:
        res = await session.execute(select(User.telegram_id).where(User.telegram_id != user_id))
        todos = res.scalars().all()
        for uid in todos:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=(
                        f"📢 Hey! {alias} está en LIVE 🔴\n\n"
                        f"👉 Solo por entrar puedes ganar puntos.\n"
                        f"💖 Si le das 'Quiéreme' podrás ganar puntos extra (pendiente de validación)."
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            "🔴 Ver live en vivo", callback_data="ver_live")],
                        [InlineKeyboardButton(
                            "🔙 Regresar al menú principal", callback_data="menu_principal")]
                    ])
                )
            except Exception as e:
                print(f"No se pudo notificar a {uid}: {e}")

    await update.message.reply_text("✅ Live registrado, publicado y notificado a la comunidad.", reply_markup=back_to_menu_keyboard())
    context.user_data["state"] = None

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
        session.add(Movimiento(telegram_id=user_id,
                    detalle="Subir video", puntos=-5))
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
        alias = user.tiktok_user if user and user.tiktok_user else (
            f"@{update.effective_user.username}" if update.effective_user.username else str(user_id))
        canal_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📺 Ver videos", callback_data="ver_video")],
            [InlineKeyboardButton(
                "🔙 Regresar al menú principal", callback_data="menu_principal")]
        ])
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📢 Nuevo video ({tipo}) publicado por {alias}\n📌 {titulo}\n📝 {descripcion}\n🔗 {link}",
            reply_markup=canal_markup
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

    texto = (
        "👀 Seguimiento disponible:\n"
        f"🔗 {seg.link}\n"
        f"🗓️ {seg.created_at}\n\n"
        "Primero entra al perfil y sigue al usuario.\n"
        "Recuerda no dejar de seguir inmediatamente después de ganar los puntos, "
        "si lo haces y te detecta el algoritmo puede ser baneo permanente."
    )

    # Mostrar botones: abrir link y regresar
    await context.bot.send_message(
        chat_id=chat_id,
        text=texto,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Ir al perfil", url=seg.link)],
            [InlineKeyboardButton(
                "🔙 Regresar al menú principal", callback_data="menu_principal")]
        ])
    )

    # Guardar hora de inicio
    context.user_data["seguimiento_opened"] = datetime.utcnow()

    # Mostrar confirmaciones después de 20 segundos
    context.job_queue.run_once(
        lambda _: context.bot.send_message(
            chat_id=chat_id,
            text="✅ Ya puedes confirmar tu apoyo:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ Ya lo seguí", callback_data=f"seguimiento_done_{seg.id}")],
                [InlineKeyboardButton(
                    "🔙 Regresar al menú principal", callback_data="menu_principal")]
            ])
        ),
        when=20
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
            .where(Video.telegram_id != user_id)   # no mostrar videos propios
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

    vid = rows[0]  # tomar el más reciente

    texto = (
        f"📺 Video ({vid.tipo}):\n"
        f"📌 {vid.titulo}\n"
        f"📝 {vid.descripcion}\n"
        f"🔗 {vid.link}\n"
        f"🗓️ {vid.created_at}\n\n"
        "⚠️ Recuerda dar like y compartir. El dueño supervisará tu apoyo.\n\n"
        "Primero entra al video y apóyalo."
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=texto,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Ir al video", url=vid.link)],
            [InlineKeyboardButton(
                "🔙 Regresar al menú principal", callback_data="menu_principal")]
        ])
    )

    # Guardar hora de inicio
    context.user_data["video_start_time"] = datetime.utcnow()

    # Mostrar confirmaciones después de 20 segundos
    context.job_queue.run_once(
        lambda _: context.bot.send_message(
            chat_id=chat_id,
            text="✅ Ya puedes confirmar tu apoyo:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⭐ Ya di like y compartí", callback_data=f"video_support_done_{vid.id}")],
                [InlineKeyboardButton(
                    "🔙 Regresar al menú principal", callback_data="menu_principal")]
            ])
        ),
        when=20
    )

# --- Ver lives (no propios, solo una vez) ---


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
            select(Live)
            .where(Live.telegram_id != user_id)   # no mostrar lives propios
            .order_by(Live.created_at.desc())
        )
        rows = res.scalars().all()

    if not rows:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ No hay lives disponibles por ahora.",
            reply_markup=back_to_menu_keyboard()
        )
        return

    live = rows[0]  # tomar el más reciente

    texto = (
        f"🎤 Live:\n"
        f"📌 {live.titulo}\n"
        f"🔗 {live.link}\n"
        f"🗓️ {live.created_at}\n\n"
        "⚠️ Recuerda ver el live y dar Quiéreme si aplica.\n\n"
        "Presiona el botón para abrir el live y empezar el conteo."
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=texto,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Ir al live", url=live.link)],
            [InlineKeyboardButton("▶️ Confirmar live",
                                  callback_data=f"live_opened_{live.id}")],
            [InlineKeyboardButton(
                "🔙 Regresar al menú principal", callback_data="menu_principal")]
        ])
    )

    # Aquí sí se espera 2 minutos (120 segundos)
    context.user_data["live_opened"] = datetime.utcnow()
    context.job_queue.run_once(
        lambda _: context.bot.send_message(
            chat_id=chat_id,
            text="✅ Ya puedes confirmar tu apoyo en el live:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "👀 Ya vi el live", callback_data=f"live_view_{live.id}")],
                [InlineKeyboardButton(
                    "❤️ Vi el live y di Quiéreme", callback_data=f"live_quiereme_{live.id}")],
                [InlineKeyboardButton(
                    "🔙 Regresar al menú principal", callback_data="menu_principal")]
            ])
        ),
        when=120
    )
    # acreditar puntos al actor


async def handle_live_view(query, context: ContextTypes.DEFAULT_TYPE, live_id: int):
    user_id = query.from_user.id

    # Verificar si ya pasaron 2 minutos desde que se mostró el live
    start_time = context.user_data.get("live_start_time")
    if start_time:
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        if elapsed < 120:   # menos de 2 minutos
            await query.answer("⏱️ Aún no cumples los 2 minutos, regresa al live.", show_alert=True)
            return

    async with async_session() as session:
        res_live = await session.execute(select(Live).where(Live.id == live_id))
        live = res_live.scalars().first()
        if not live:
            await query.edit_message_text("❌ Live no encontrado.", reply_markup=back_to_menu_keyboard())
            return
        if live.telegram_id == user_id:
            await query.answer("No puedes apoyar tu propio live.", show_alert=True)
            return

        # Registrar interacción automática (aprobada de inmediato)
        inter = Interaccion(
            tipo="live_view",
            item_id=live.id,
            actor_id=user_id,
            owner_id=live.telegram_id,
            status="accepted",   # 👈 directo a aceptado
            puntos=PUNTOS_LIVE_SOLO_VER
        )
        session.add(inter)

        # acreditar puntos al actor
        res_actor = await session.execute(select(User).where(User.telegram_id == user_id))
        actor = res_actor.scalars().first()
        if actor:
            actor.balance = (actor.balance or 0) + PUNTOS_LIVE_SOLO_VER
            session.add(Movimiento(
                telegram_id=user_id,
                detalle="Apoyo live (solo ver)",
                puntos=PUNTOS_LIVE_SOLO_VER
            ))

        await session.commit()

    await query.edit_message_text("✅ Tu apoyo de ver el live fue acreditado automáticamente.", reply_markup=back_to_menu_keyboard())


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

        inter = Interaccion(
            tipo="live_quiereme",
            item_id=live.id,
            actor_id=user_id,
            owner_id=live.telegram_id,
            status="pending",
            puntos=PUNTOS_LIVE_SOLO_VER + PUNTOS_LIVE_QUIEREME_EXTRA
        )
        session.add(inter)
        await session.commit()

        # obtener TikTok del actor
        res_actor = await session.execute(select(User).where(User.telegram_id == user_id))
        actor = res_actor.scalars().first()

        # Notificar al dueño para aprobar/rechazar
        await notify_user(
            context,
            chat_id=live.telegram_id,
            text=(
                f"📩 Nuevo apoyo a tu live:\n"
                f"Item ID: {live.id}\n"
                f"Actor: {user_id}\n"
                f"Usuario TikTok: {actor.tiktok_user or 'no registrado'}\n"
                f"Puntos: {PUNTOS_LIVE_SOLO_VER + PUNTOS_LIVE_QUIEREME_EXTRA}\n\n"
                "¿Apruebas que te dio el Quiéreme?"
            ),
            reply_markup=yes_no_keyboard(
                callback_yes=f"approve_interaction_{inter.id}",
                callback_no=f"reject_interaction_{inter.id}"
            )
        )

    await query.edit_message_text("🟡 Tu apoyo fue registrado y está pendiente de aprobación del dueño.", reply_markup=back_to_menu_keyboard())
# --- Registrar interacción de seguimiento (notifica con TikTok del actor) ---


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

        # obtener TikTok del actor
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
            mov = Movimiento(telegram_id=inter.actor_id,
                             detalle=f"Apoyo {inter.tipo} aprobado", puntos=inter.puntos)
            session.add(mov)
            if actor.referrer_id:
                res_ref = await session.execute(select(User).where(User.telegram_id == actor.referrer_id))
                referrer = res_ref.scalars().first()
                if referrer:
                    referrer.balance = (
                        referrer.balance or 0) + PUNTOS_REFERIDO_BONUS
                    session.add(Movimiento(
                        telegram_id=referrer.telegram_id,
                        detalle="Bonus por referido",
                        puntos=PUNTOS_REFERIDO_BONUS
                    ))
                    await notify_user(
                        context,
                        chat_id=referrer.telegram_id,
                        text=f"💸 Recibiste {PUNTOS_REFERIDO_BONUS} puntos por la interacción aceptada de tu referido {actor.telegram_id}.",
                        reply_markup=back_to_menu_keyboard()   # 👈 Agregado
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


# --- Registrar interacción de video (notifica con TikTok del actor) ---

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

        # ✅ Verificar si ya existe interacción
        res_inter = await session.execute(
            select(Interaccion).where(
                Interaccion.tipo == "video_support",
                Interaccion.item_id == vid.id,
                Interaccion.actor_id == user_id
            )
        )
        inter_existente = res_inter.scalars().first()
        if inter_existente:
            await query.answer("⚠️ Ya registraste apoyo en este video.", show_alert=True)
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

        # obtener TikTok del actor
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
        # ✅ Validar duplicados antes de insertar
        res = await session.execute(select(SubAdmin).where(SubAdmin.telegram_id == sub_id))
        exists = res.scalars().first()
        if exists:
            await update.message.reply_text("⚠️ Ya es subadmin.")
            return

        session.add(SubAdmin(telegram_id=sub_id))
        await session.commit()

    # Mensaje al admin que ejecutó el comando
    await update.message.reply_text(f"✅ Subadmin agregado: {sub_id}")

    # ✅ Notificación al subadmin agregado con mensajes explicativos
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
        if u.telegram_id == ADMIN_ID:
            texto += f"👑 Admin dueño: ID {u.telegram_id}, TikTok: {u.tiktok_user}, Balance: {u.balance}\n"
        elif await is_subadmin(u.telegram_id):
            texto += f"🛡️ Subadmin: ID {u.telegram_id}, TikTok: {u.tiktok_user}, Balance: {u.balance}\n"
        else:
            texto += f"- Usuario: ID {u.telegram_id}, TikTok: {u.tiktok_user}, Balance: {u.balance}\n"

    await update.message.reply_text(texto)


# --- Gestión de Cupones ---
# --- Gestión de Cupones  subir---
async def subir_cupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # Solo admin o subadmin pueden crear
    if uid != ADMIN_ID and not await is_subadmin(uid):
        await update.message.reply_text("❌ No tienes permiso para crear cupones.")
        return

    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Uso: /subir_cupon <puntos> <ganadores> <codigo>")
        return

    try:
        puntos = float(args[0])
        ganadores = int(args[1])
        codigo = args[2].strip()
    except Exception:
        await update.message.reply_text("⚠️ Parámetros inválidos.")
        return

    async with async_session() as session:
        # Verificar si ya existe
        res = await session.execute(select(Cupon).where(Cupon.codigo == codigo))
        existe = res.scalars().first()
        if existe:
            await update.message.reply_text("⚠️ Ese código ya existe.")
            return

        cupon = Cupon(codigo=codigo, puntos=puntos,
                      ganadores=ganadores, creado_por=uid)
        session.add(cupon)
        await session.commit()

    await update.message.reply_text(
        f"✅ Se subió cupón con éxito\n• Código: {codigo}\n• Puntos: {puntos:.2f}\n• Ganadores: {ganadores}"
    )

# --- Gestión de Cupones cobrar ---


async def cobrar_cupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Uso: /cobrar_cupon <codigo>")
        return

    codigo = args[0].strip()
    uid = update.effective_user.id

    async with async_session() as session:
        res = await session.execute(select(Cupon).where(Cupon.codigo == codigo))
        cupon = res.scalars().first()
        if not cupon:
            await update.message.reply_text("❌ Cupón no encontrado.")
            return

        if cupon.usados >= cupon.ganadores:
            await update.message.reply_text("⚠️ Cupón agotado.")
            return

        # Verificar si ya lo cobró
        res_claim = await session.execute(
            select(CuponClaim).where(CuponClaim.codigo ==
                                     codigo, CuponClaim.telegram_id == uid)
        )
        ya_cobrado = res_claim.scalars().first()
        if ya_cobrado:
            await update.message.reply_text("⚠️ Ya cobraste este cupón.")
            return

        # Verificar usuario
        res_u = await session.execute(select(User).where(User.telegram_id == uid))
        user = res_u.scalars().first()
        if not user:
            await update.message.reply_text("❌ No estás registrado. Usa /start primero.")
            return

        # Acreditar puntos
        user.balance = (user.balance or 0) + (cupon.puntos or 0)
        session.add(Movimiento(telegram_id=uid,
                    detalle=f"Cobro cupón {codigo}", puntos=cupon.puntos))
        cupon.usados += 1
        session.add(CuponClaim(codigo=codigo, telegram_id=uid))
        await session.commit()

    await update.message.reply_text(
        f"✅ Se cobró cupón con éxito\n• Código: {codigo}\n• Puntos sumados: {cupon.puntos:.2f}",
        reply_markup=back_to_menu_keyboard()   # 👈 aquí agregamos el botón

    )


# --- Acciones administrativas propuestas por subadmin ---

# --- Notificación al admin ---


async def notify_admin(context, text: str, action_id: int = None):
    if action_id:
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Aprobar", callback_data=f"approve_action_{action_id}"),
                InlineKeyboardButton(
                    "❌ Rechazar", callback_data=f"reject_action_{action_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
    else:
        reply_markup = None

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=text,
            reply_markup=reply_markup
        )
    except Exception as e:
        print("No se pudo notificar al admin:", e)


async def dar_puntos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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

    # ✅ Si el dueño ejecuta, se aplica directo sin aprobación
    if user_id == ADMIN_ID:
        async with async_session() as session:
            res_u = await session.execute(select(User).where(User.telegram_id == target_id))
            u = res_u.scalars().first()
            if u:
                u.balance = (u.balance or 0) + cantidad
                session.add(Movimiento(
                    telegram_id=u.telegram_id,
                    detalle=f"🎁 Puntos otorgados por admin",
                    puntos=cantidad
                ))
                await session.commit()

        # Mensaje al admin
        await update.message.reply_text(f"🎁 El admin otorgó {cantidad} puntos a ID {target_id}.")

        # ✅ Notificación al usuario que recibió los puntos
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"🎁 Has recibido {cantidad} puntos directamente del administrador."
            )
        except Exception as e:
            print(f"No se pudo notificar al usuario {target_id}: {e}")
        return

    # ✅ Si es subadmin, se crea acción pendiente de aprobación
    if await is_subadmin(user_id):
        expires = datetime.utcnow() + timedelta(days=AUTO_APPROVE_AFTER_DAYS)
        async with async_session() as session:
            action = AdminAction(
                tipo="dar_puntos",
                target_id=target_id,
                cantidad=cantidad,
                subadmin_id=user_id,
                status="pending",
                expires_at=expires,
                # 👈 aquí usamos note en lugar de detalle
                note=f"Dar {cantidad} puntos a {target_id}"
            )
            session.add(action)
            await session.commit()
            # 👈 para obtener el ID recién creado
            await session.refresh(action)
        await update.message.reply_text(
            f"🟡 Acción propuesta: dar {cantidad} puntos a {target_id}. Queda pendiente de aprobación del admin."
        )

        await notify_admin(
            context,
            text=f"🟡 Acción pendiente: dar {cantidad} puntos a {target_id}.",
            action_id=action.id   # 👈 ahora sí pasamos el ID
        )

    else:
        await update.message.reply_text("❌ No tienes permiso para usar este comando.")
# --- Gestión de acciones pendientes ---


async def handle_action_approve(query, context, action_id: int):
    async with async_session() as session:
        res = await session.execute(select(AdminAction).where(AdminAction.id == action_id))
        action = res.scalars().first()
        if not action:
            await query.edit_message_text("⚠️ Acción no encontrada.")
            return

        if action.status != "pending":
            await query.edit_message_text(f"⚠️ Esta acción ya está en estado: {action.status}.")
            return

        # 👇 Aplicar la acción si es dar_puntos
        if action.tipo == "dar_puntos":
            res_u = await session.execute(select(User).where(User.telegram_id == action.target_id))
            u = res_u.scalars().first()
            if u:
                u.balance = (u.balance or 0) + action.cantidad
                session.add(Movimiento(
                    telegram_id=u.telegram_id,
                    detalle=f"🎁 Puntos otorgados por aprobación de admin",
                    puntos=action.cantidad
                ))
                await session.commit()
                await notify_user(
                    context,
                    chat_id=u.telegram_id,
                    text=f"🎁 Tu acción fue aprobada. Recibiste {action.cantidad} puntos."
                )

        action.status = "accepted"
        await session.commit()

    await query.edit_message_text("✅ Acción aprobada y aplicada.")


async def handle_action_reject(query, context, action_id: int):
    async with async_session() as session:
        res = await session.execute(select(AdminAction).where(AdminAction.id == action_id))
        action = res.scalars().first()
        if not action:
            await query.edit_message_text("⚠️ Acción no encontrada.")
            return

        if action.status != "pending":
            await query.edit_message_text(f"⚠️ Esta acción ya está en estado: {action.status}.")
            return

        action.status = "rejected"
        await session.commit()
        await session.refresh(action)   # 👈 obtener ID recién creado
        await query.edit_message_text("❌ Acción rechazada.")


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
    # Verificamos que solo el ADMIN_ID pueda aprobar
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Solo el admin puede aprobar.", show_alert=True)
        return

    async with async_session() as session:
        # Buscar la acción en la base de datos
        res = await session.execute(select(AdminAction).where(AdminAction.id == action_id))
        action = res.scalars().first()

        # Si no existe la acción
        if not action:
            await query.edit_message_text(
                "❌ Acción no encontrada.",
                reply_markup=back_to_menu_keyboard()
            )
            return

        # Si la acción ya no está pendiente
        if action.status != "pending":
            await query.edit_message_text(
                f"⚠️ Acción ya está en estado: {action.status}.",
                reply_markup=back_to_menu_keyboard()
            )
            return

        # Si la acción es dar puntos
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

        # Si la acción es cambiar el alias de TikTok
        elif action.tipo == "cambiar_tiktok":
            res_u = await session.execute(select(User).where(User.telegram_id == action.target_id))
            u = res_u.scalars().first()
            if u and action.nuevo_alias:
                u.tiktok_user = action.nuevo_alias

        # Actualizamos el estado a aceptado y guardamos
        action.status = "accepted"
        await session.commit()

    # Mensaje final con botón de regreso al menú principal
    await query.edit_message_text(
        "✅ Acción administrativa aprobada y aplicado el cambio.",
        reply_markup=back_to_menu_keyboard()
    )


async def reject_admin_action(query, context: ContextTypes.DEFAULT_TYPE, action_id: int):
    # Verificamos que solo el ADMIN_ID pueda rechazar
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Solo el admin puede rechazar.", show_alert=True)
        return

    async with async_session() as session:
        # Buscar la acción en la base de datos
        res = await session.execute(select(AdminAction).where(AdminAction.id == action_id))
        action = res.scalars().first()

        # Si no existe la acción
        if not action:
            await query.edit_message_text(
                "❌ Acción no encontrada.",
                reply_markup=back_to_menu_keyboard()
            )
            return

        # Si la acción ya no está pendiente
        if action.status != "pending":
            await query.edit_message_text(
                f"⚠️ Acción ya está en estado: {action.status}.",
                reply_markup=back_to_menu_keyboard()
            )
            return

        # Actualizamos el estado a rechazado y guardamos
        action.status = "rejected"
        await session.commit()

    # Mensaje final con botón de regreso al menú principal
    await query.edit_message_text(
        "❌ Acción administrativa rechazada.",
        reply_markup=back_to_menu_keyboard()
    )

# bot.py (Parte 5/5)


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass

    data = query.data
    print("Callback recibido:", data)   # 👈 Depuración: ver qué callback llega

    if data == "subir_seguimiento":
        await query.edit_message_text(
            "🔗 Envía tu link de perfil de TikTok para publicar tu seguimiento (costo: 3 puntos).",
            reply_markup=back_to_menu_keyboard()
        )
        context.user_data["state"] = "seguimiento_link"

    # --- Callback principal (menú y acciones) ---
    elif data == "subir_video":
        keyboard = [
            [InlineKeyboardButton(
                "🎬 Normal", callback_data="video_tipo_normal")],
            [InlineKeyboardButton("🎤 Incentivo Live",
                                  callback_data="video_tipo_live")],
            [InlineKeyboardButton(
                "🎉 Evento", callback_data="video_tipo_evento")],
            [InlineKeyboardButton(
                "🛍️ TikTok Shop", callback_data="video_tipo_shop")],
            [InlineKeyboardButton(
                "🤝 Colaboración", callback_data="video_tipo_colaboracion")],
            [InlineKeyboardButton(
                "🔙 Regresar al menú principal", callback_data="menu_principal")]
        ]
        await query.edit_message_text(
            "📌 ¿Qué tipo de video quieres subir?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
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
        return   # 👈 agregado para cortar el flujo aquí

    # 👇 Bloques de Seguimiento
    elif data == "ver_seguimiento":
        await show_seguimientos(query, context)

    elif data.startswith("seguimiento_opened_"):
        seg_id = int(data.split("_")[-1])
        # ✅ corregido
        context.user_data["seguimiento_opened"] = datetime.utcnow()
        await query.edit_message_text(
            "✅ Perfil abierto, espera 20 segundos antes de confirmar.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ Ya lo seguí", callback_data=f"seguimiento_done_{seg_id}")],
                [InlineKeyboardButton(
                    "🔙 Regresar al menú principal", callback_data="menu_principal")]
            ])
        )

    elif data.startswith("seguimiento_done_"):
        seg_id = int(data.split("_")[-1])
        start_time = context.user_data.get("seguimiento_opened")   # ✅ coincide
        if start_time and (datetime.utcnow() - start_time).seconds >= 20:
            await handle_seguimiento_done(query, context, seg_id)
        else:
            await query.answer("⚠️ Primero abre el perfil y espera 20 segundos.")

    # 👇 Bloques de Video
    elif data == "ver_video":
        await show_videos(query, context)

    elif data.startswith("video_go_"):
        vid_id = int(data.split("_")[-1])
        # ✅ correcto
        context.user_data["video_start_time"] = datetime.utcnow()

        await query.answer("⏱️ Has abierto el video. Espera 20 segundos...")

        job_name = f"video_confirm_{vid_id}_{query.from_user.id}"
        old_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in old_jobs:
            job.schedule_removal()

        context.job_queue.run_once(
            lambda _: context.bot.send_message(
                chat_id=query.message.chat.id,
                text="✅ Ya puedes confirmar tu apoyo:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "⭐ Ya di like y compartí", callback_data=f"video_support_done_{vid_id}")],
                    [InlineKeyboardButton(
                        "🔙 Regresar al menú principal", callback_data="menu_principal")]
                ])
            ),
            when=20,
            name=job_name
        )

    elif data.startswith("video_support_done_"):
        vid_id = int(data.split("_")[-1])
        start_time = context.user_data.get("video_start_time")   # ✅ coincide
        if start_time and (datetime.utcnow() - start_time).seconds >= 20:
            await handle_video_support_done(query, context, vid_id)
        else:
            await query.answer("⚠️ Primero abre el video y espera 20 segundos.")

    # 👇 Bloques de Live
    elif data == "ver_live":
        await show_lives(query, context)

    elif data.startswith("live_opened_"):
        live_id = int(data.split("_")[-1])
        context.user_data["live_opened"] = datetime.utcnow()   # ✅ corregido
        await query.edit_message_text(
            "✅ Live abierto, espera 2 minutos antes de confirmar.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "👀 Ya vi el live", callback_data=f"live_view_{live_id}")],
                [InlineKeyboardButton(
                    "❤️ Vi el live y di Quiéreme", callback_data=f"live_quiereme_{live_id}")],
                [InlineKeyboardButton(
                    "🔙 Regresar al menú principal", callback_data="menu_principal")]
            ])
        )

    elif data.startswith("live_view_"):
        live_id = int(data.split("_")[-1])
        start_time = context.user_data.get("live_opened")   # ✅ coincide
        if start_time and (datetime.utcnow() - start_time).seconds >= 120:
            await handle_live_view(query, context, live_id)
        else:
            await query.answer("⚠️ Primero abre el live y espera 2 minutos.")

    elif data.startswith("live_quiereme_"):
        live_id = int(data.split("_")[-1])
        start_time = context.user_data.get("live_opened")   # ✅ coincide
        if start_time and (datetime.utcnow() - start_time).seconds >= 120:
            await handle_live_quiereme(query, context, live_id)
        else:
            await query.answer("⚠️ Primero abre el live y espera 2 minutos.")

    # 👇 Bloques de Interacciones (Aceptar/Rechazar)
    elif data.startswith("approve_interaction_"):
        inter_id = int(data.split("_")[-1])
        await approve_interaction(query, context, inter_id)

    elif data.startswith("reject_interaction_"):
        inter_id = int(data.split("_")[-1])
        await reject_interaction(query, context, inter_id)

    # 👇 Bloques de Balance, Comandos y Mi link
    elif data == "balance":
        await show_balance(query, context)

    elif data == "comandos":
        await comandos(query, context)

    elif data == "mi_ref_link":
        await show_my_ref_link(query, context)

    elif data == "menu_principal":
        await show_main_menu(query, context)
        return

    # 👇 Bloques de Cupones
    elif data == "subir_cupon":
        await query.edit_message_text(
            "✍️ Envía el comando:\n/subir_cupon <puntos> <ganadores> <codigo>\n\nEjemplo:\n/subir_cupon 2.5 100 BIENVENIDO2026",
            reply_markup=back_to_menu_keyboard()
        )

    elif data == "cobrar_cupon":
        await query.edit_message_text(
            "💳 Ingresa el código del cupón:",
            reply_markup=back_to_menu_keyboard()
        )
        context.user_data["state"] = "cobrar_cupon"

    elif data == "subir_live":
        await query.edit_message_text(
            "🔗 Envía el link de tu live de TikTok (costo: 3 puntos).",
            reply_markup=back_to_menu_keyboard()
        )
        context.user_data["state"] = "live_link"

    # 👇 Bloques de Referidos
    elif data == "resumen_referidos":
        await referral_weekly_summary(query, context)
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
    elif state == "live_link":   # 👈 corregido
        await save_live_link(update, context)
    elif state == "video_title":
        await save_video_title(update, context)
    elif state == "video_desc":
        await save_video_desc(update, context)
    elif state == "video_link":
        await save_video_link(update, context)
    elif state == "cobrar_cupon":
        context.args = [update.message.text.strip()]
        await cobrar_cupon(update, context)
        context.user_data["state"] = None
    else:
        await update.message.reply_text(
            "⚠️ Usa el menú para interactuar con el bot.\n\nSi es tu primera vez, escribe /start.",
            reply_markup=back_to_menu_keyboard()
        )

# --- Guardar video con lógica especial TikTok Shop ---


async def save_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    user_id = update.effective_user.id

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user_id))
        user = res.scalars().first()
        if not user:
            await update.message.reply_text(
                "❌ No estás registrado. Usa /start primero.",
                reply_markup=back_to_menu_keyboard()
            )
            context.user_data["state"] = None
            return

        # Crear el video en DB
        video = Video(
            telegram_id=user_id,
            tipo=context.user_data.get("video_tipo"),
            titulo=context.user_data.get("video_title"),
            descripcion=context.user_data.get("video_desc"),
            link=link
        )
        session.add(video)
        await session.commit()

    # 👉 Lógica especial para TikTok Shop
    if context.user_data.get("video_tipo") == "TikTok Shop":
        await context.bot.send_message(
            chat_id=-1003664738296,   # canal de ofertas
            text=f"📢 No te pierdas esta oferta imperdible de TikTok Shop\n\n"
                 f"📌 {context.user_data.get('video_title')}\n"
                 f"📝 {context.user_data.get('video_desc')}\n"
                 # 👈 incluir el link en el texto para que Telegram genere la preview
                 f"{link}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛍️ Entra y compra", url=link)]
            ])
        )
    else:
        # Publicar en canal normal sin botones
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🎬 Nuevo video subido:\n\n"
                 f"📌 {context.user_data.get('video_title')}\n"
                 f"📝 {context.user_data.get('video_desc')}\n"
                 f"{link}"
        )

    await update.message.reply_text(
        "✅ Video guardado con éxito.",
        reply_markup=back_to_menu_keyboard()
    )
    context.user_data["state"] = None
    # await show_main_menu(update, context)


# --- Comando: lista de comandos ---
async def comandos(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    texto = (
        "📋 Lista de comandos disponibles:\n\n"
        "• /start - Iniciar el bot y registrarte\n"
        "• /balance - Ver tu balance de puntos\n"
        "• /mi_ref_link - Obtener tu link de referidos\n"
        "• /listar_usuarios - Ver lista de usuarios (solo admin)\n\n"
        "👥 Gestión de subadmins:\n"
        "• /add_subadmin <telegram_id> - Agregar subadmin (solo dueño)\n"
        "• /remove_subadmin <telegram_id> - Quitar subadmin (solo dueño)\n\n"
        "🎬 Videos:\n"
        "• Subir video desde el menú principal\n"
        "• Apoyar videos para ganar puntos\n\n"
        "🔴 Lives:\n"
        "• Subir live desde el menú principal (costo: 3 puntos)\n"
        "• Apoyar lives para ganar puntos\n"
        "• Dar 'Quiéreme' en un live para puntos extra (pendiente de validación)\n\n"
        "🎁 Cupones:\n"
        "• /subir_cupon <puntos> <ganadores> <codigo> - Crear cupón (admin o subadmin)\n"
        "🛡️ Acciones administrativas:\n"
        "• /dar_puntos <telegram_id> <cantidad> - Dar puntos (dueño directo, subadmin con aprobación)\n"
        "• /cambiar_tiktok_usuario <telegram_id> <nuevo_alias_con_@> - Cambiar alias TikTok (subadmin con aprobación)\n"
    )

    # ✅ Mantener tu estructura para que funcione desde comando y menú
    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(texto, reply_markup=back_to_menu_keyboard())
    else:
        await update_or_query.edit_message_text(texto, reply_markup=back_to_menu_keyboard())


# --- Comando: mi link de referido ---
async def cmd_my_ref_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_my_ref_link(update, context)


# --- Main ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")


async def preflight():
    await init_db()
    await migrate_db()

loop = asyncio.get_event_loop()
loop.run_until_complete(preflight())


# --- Función de inicio para job_queue ---
async def on_startup(app: Application):
    # Solo dejamos la tarea de auto-aprobación
    app.job_queue.run_repeating(lambda _: auto_approve_loop(app),
                                interval=AUTO_APPROVE_INTERVAL_SECONDS, first=5)


# ✅ Opción 1: definir on_startup antes de construir la aplicación
application = Application.builder().token(
    BOT_TOKEN).post_init(on_startup).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("inicio", start))
application.add_handler(CommandHandler("balance", cmd_balance))
application.add_handler(CommandHandler("listar_usuarios", listar_usuarios))
application.add_handler(CommandHandler("dar_puntos", dar_puntos))
application.add_handler(CommandHandler("cambiar_tiktok", cambiar_tiktok))
application.add_handler(CommandHandler(
    "cambiar_tiktok_usuario", cambiar_tiktok_usuario))
application.add_handler(CommandHandler("add_subadmin", add_subadmin))
application.add_handler(CommandHandler("remove_subadmin", remove_subadmin))
application.add_handler(CommandHandler("subir_cupon", subir_cupon))
application.add_handler(CommandHandler("cobrar_cupon", cobrar_cupon))
application.add_handler(CommandHandler("mi_ref_link", cmd_my_ref_link))
application.add_handler(CommandHandler("comandos", comandos))
application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND, text_handler))
application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND, text_handler))
application.add_handler(CallbackQueryHandler(menu_handler))

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
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        url_path=BOT_TOKEN,
        webhook_url=f"https://{RENDER_EXTERNAL_HOSTNAME}/{BOT_TOKEN}"
    )
