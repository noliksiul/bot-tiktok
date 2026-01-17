# bot.py (Parte 1/5)

import os, asyncio, secrets
from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, BigInteger, Boolean, DateTime, Float, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from flask import Flask, request

# Configuración DB
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
Base = declarative_base()
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Constantes
ADMIN_ID = 890166032
CHANNEL_URL = "https://t.me/tu_canal"
GROUP_URL = "https://t.me/tu_grupo"
PUNTOS_APOYO_SEGUIMIENTO = 1
PUNTOS_APOYO_VIDEO = 2
PUNTOS_REFERIDO_BONUS = 1
AUTO_APPROVE_AFTER_DAYS = 2

# --- Modelos ---
class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    tiktok_user = Column(String, nullable=True)
    balance = Column(Integer, default=0)
    referral_code = Column(String, nullable=True)
    referrer_id = Column(BigInteger, nullable=True)
    is_subadmin = Column(Boolean, default=False)  # ✅ corregido

class Movimiento(Base):
    __tablename__ = "movimientos"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=False)
    detalle = Column(String, nullable=False)
    puntos = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

class Seguimiento(Base):
    __tablename__ = "seguimientos"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=False)
    link = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=False)
    tipo = Column(String, nullable=False)
    titulo = Column(String, nullable=True)
    descripcion = Column(String, nullable=True)
    link = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Interaccion(Base):
    __tablename__ = "interacciones"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tipo = Column(String, nullable=False)
    item_id = Column(Integer, nullable=False)
    actor_id = Column(BigInteger, nullable=False)
    owner_id = Column(BigInteger, nullable=False)
    status = Column(String, default="pending")
    puntos = Column(Float, default=0.0)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class AdminAction(Base):
    __tablename__ = "admin_actions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tipo = Column(String, nullable=False)
    actor_id = Column(BigInteger, nullable=False)
    target_id = Column(BigInteger, nullable=False)
    cantidad = Column(Integer, nullable=True)
    nuevo_alias = Column(String, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

class Live(Base):
    __tablename__ = "lives"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=False)
    titulo = Column(String, nullable=True)
    descripcion = Column(String, nullable=True)
    link = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class LiveInteraccion(Base):
    __tablename__ = "live_interacciones"
    id = Column(Integer, primary_key=True, autoincrement=True)
    live_id = Column(Integer, nullable=False)
    actor_id = Column(BigInteger, nullable=False)
    tipo = Column(String, nullable=False)  # "view" o "gift"
    status = Column(String, default="pending")
    puntos = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

# --- Migración ---
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def migrate_db():
    # Aquí puedes añadir lógica de migración si cambias columnas
    pass
# bot.py (Parte 2/5)

# --- Menú principal ---
async def show_main_menu(update_or_query, context, message="🏠 Menú principal:"):
    keyboard = [
        [InlineKeyboardButton("📈 Subir seguimiento", callback_data="subir_seguimiento")],
        [InlineKeyboardButton("🎥 Subir video", callback_data="subir_video")],
        [InlineKeyboardButton("🎙️ Subir live", callback_data="subir_live")],
        [InlineKeyboardButton("🔴 Ver live (en vivo)", callback_data="ver_live")],
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

# --- Start con saludo y registro de referido ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args if hasattr(context, "args") else []
    ref_code = None
    if args:
        token = args[0]
        if token.startswith("ref_"):
            ref_code = token.replace("ref_", "").strip()

    async with async_session() as session:
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

    if not user or not user.tiktok_user:
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

    await update.message.reply_text("✅ Seguimiento subido con éxito.", reply_markup=back_to_menu_keyboard())
    context.user_data["state"] = None
    await show_main_menu(update, context)

# --- Flujo de subir video ---
async def save_video_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["video_title"] = update.message.text.strip()
    context.user_data["state"] = "video_desc"
    await update.message.reply_text("📝 Ahora envíame la descripción del video:", reply_markup=back_to_menu_keyboard())

async def save_video_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["video_desc"] = update.message.text.strip()
    context.user_data["state"] = "video_link"
    await update.message.reply_text("🔗 Ahora envíame el link del video:", reply_markup=back_to_menu_keyboard())

async def save_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    user_id = update.effective_user.id
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
            tipo=context.user_data.get("video_tipo", "Normal"),
            titulo=context.user_data.get("video_title", ""),
            descripcion=context.user_data.get("video_desc", ""),
            link=link
        )
        session.add(vid)
        user.balance = (user.balance or 0) - 5
        mov = Movimiento(telegram_id=user_id, detalle="Subir video", puntos=-5)
        session.add(mov)
        await session.commit()

    await update.message.reply_text("✅ Video subido con éxito.", reply_markup=back_to_menu_keyboard())
    context.user_data.clear()
    await show_main_menu(update, context)

# --- Subir Live ---
async def save_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            await update.message.reply_text("⚠️ No tienes suficientes puntos para subir un Live (mínimo 3).", reply_markup=back_to_menu_keyboard())
            context.user_data["state"] = None
            return

        live = Live(telegram_id=user_id, link=link, titulo="Live en TikTok", descripcion="Transmisión en vivo")
        session.add(live)
        user.balance = (user.balance or 0) - 3
        mov = Movimiento(telegram_id=user_id, detalle="Subir Live", puntos=-3)
        session.add(mov)
        await session.commit()

    await update.message.reply_text("✅ Tu Live se subió con éxito.", reply_markup=back_to_menu_keyboard())
    context.user_data["state"] = None

    # Notificar a todos los usuarios (excepto al dueño)
    async with async_session() as session:
        res = await session.execute(select(User.telegram_id))
        usuarios = [row[0] for row in res.all()]
        res_owner = await session.execute(select(User).where(User.telegram_id == user_id))
        owner = res_owner.scalars().first()
        alias = owner.tiktok_user or f"ID {user_id}"

    for uid in usuarios:
        if uid != user_id:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"📢 El usuario {alias} está en línea.\nPuedes ganar hasta 1.5 puntos uniéndote a su Live."
                )
            except Exception as e:
                print("Aviso: no se pudo notificar a un usuario sobre el Live:", e)
# bot.py (Parte 3/5 - Bloque 1)

# --- Ver seguimientos ---
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
    await context.bot.send_message(chat_id=chat_id, text=texto, reply_markup=InlineKeyboardMarkup(keyboard))

# --- Ver videos ---
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
        "Pulsa el botón si ya apoyaste."
    )
    await context.bot.send_message(chat_id=chat_id, text=texto, reply_markup=InlineKeyboardMarkup(keyboard))

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

# bot.py (Parte 3/5 - Bloque 2)

# --- Ver Lives ---
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
            .where(Live.telegram_id != user_id)
            .order_by(Live.created_at.desc())
        )
        rows = res.scalars().all()

    if not rows:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ No hay Lives disponibles por ahora.",
            reply_markup=back_to_menu_keyboard()
        )
        return

    live = rows[0]
    keyboard = [
        [InlineKeyboardButton("👀 Ya vi el Live ✅", callback_data=f"live_view_done_{live.id}")],
        [InlineKeyboardButton("🎁 Envié regalo ⭐", callback_data=f"live_gift_done_{live.id}")],
        [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]
    ]
    texto = (
        f"🔴 Live disponible:\n"
        f"📌 {live.titulo}\n"
        f"📝 {live.descripcion}\n"
        f"🔗 {live.link}\n"
        f"🗓️ {live.created_at}\n\n"
        "Pulsa el botón si ya apoyaste este Live."
    )
    await context.bot.send_message(chat_id=chat_id, text=texto, reply_markup=InlineKeyboardMarkup(keyboard))

# --- Registrar interacción de Live (view/gift) ---
async def handle_live_interaction_done(query, context: ContextTypes.DEFAULT_TYPE, live_id: int, tipo: str):
    user_id = query.from_user.id
    puntos = 1.0 if tipo == "view" else 1.5

    async with async_session() as session:
        res_live = await session.execute(select(Live).where(Live.id == live_id))
        live = res_live.scalars().first()
        if not live:
            await query.edit_message_text("❌ Live no encontrado.", reply_markup=back_to_menu_keyboard())
            return
        if live.telegram_id == user_id:
            await query.answer("No puedes apoyar tu propio Live.", show_alert=True)
            return

        inter = LiveInteraccion(
            live_id=live.id,
            actor_id=user_id,
            tipo=tipo,
            status="pending",
            puntos=puntos
        )
        session.add(inter)
        await session.commit()

        res_actor = await session.execute(select(User).where(User.telegram_id == user_id))
        actor = res_actor.scalars().first()

    await query.edit_message_text("🟡 Tu apoyo al Live fue registrado y está pendiente de aprobación del dueño.", reply_markup=back_to_menu_keyboard())
    await notify_user(
        context,
        chat_id=live.telegram_id,
        text=(
            f"📩 Nuevo apoyo a tu Live:\n"
            f"Live ID: {live.id}\n"
            f"Actor: {user_id}\n"
            f"Usuario TikTok: {actor.tiktok_user or 'no registrado'}\n"
            f"Tipo: {tipo}\n"
            f"Puntos: {puntos}\n\n"
            "¿Apruebas?"
        ),
        reply_markup=yes_no_keyboard(
            callback_yes=f"approve_live_interaction_{inter.id}",
            callback_no=f"reject_live_interaction_{inter.id}"
        )
    )

# --- Aprobar interacción de Live ---
async def approve_live_interaction(query, context: ContextTypes.DEFAULT_TYPE, live_inter_id: int):
    async with async_session() as session:
        res = await session.execute(select(LiveInteraccion).where(LiveInteraccion.id == live_inter_id))
        inter = res.scalars().first()
        if not inter:
            await query.edit_message_text("❌ Interacción de Live no encontrada.", reply_markup=back_to_menu_keyboard())
            return

        # Obtener dueño del live
        res_live = await session.execute(select(Live).where(Live.id == inter.live_id))
        live = res_live.scalars().first()
        if not live:
            await query.edit_message_text("❌ Live asociado no encontrado.", reply_markup=back_to_menu_keyboard())
            return

        if query.from_user.id != live.telegram_id:
            await query.answer("No puedes aprobar esta interacción de Live.", show_alert=True)
            return
        if inter.status != "pending":
            await query.edit_message_text(f"⚠️ Esta interacción ya está en estado: {inter.status}.", reply_markup=back_to_menu_keyboard())
            return

        inter.status = "accepted"
        res_actor = await session.execute(select(User).where(User.telegram_id == inter.actor_id))
        actor = res_actor.scalars().first()
        if actor:
            actor.balance = (actor.balance or 0) + (inter.puntos or 0)
            session.add(Movimiento(
                telegram_id=inter.actor_id,
                detalle=f"Apoyo Live ({inter.tipo}) aprobado",
                puntos=inter.puntos
            ))
            # Bonus para el referidor
            if actor.referrer_id:
                res_ref = await session.execute(select(User).where(User.telegram_id == actor.referrer_id))
                referrer = res_ref.scalars().first()
                if referrer:
                    referrer.balance = (referrer.balance or 0) + PUNTOS_REFERIDO_BONUS
                    session.add(Movimiento(
                        telegram_id=referrer.telegram_id,
                        detalle="Bonus por referido activo (Live)",
                        puntos=PUNTOS_REFERIDO_BONUS
                    ))
        await session.commit()

    await query.edit_message_text("✅ Interacción de Live aprobada y puntos acreditados.", reply_markup=back_to_menu_keyboard())
    try:
        await notify_user(
            context,
            chat_id=inter.actor_id,
            text=f"✅ Tu apoyo al Live ({inter.tipo}) fue aprobado. Se acreditaron {inter.puntos} puntos."
        )
    except Exception as e:
        print("Aviso: no se pudo notificar al actor sobre la aprobación del Live:", e)

# --- Rechazar interacción de Live ---
async def reject_live_interaction(query, context: ContextTypes.DEFAULT_TYPE, live_inter_id: int):
    async with async_session() as session:
        res = await session.execute(select(LiveInteraccion).where(LiveInteraccion.id == live_inter_id))
        inter = res.scalars().first()
        if not inter:
            await query.edit_message_text("❌ Interacción de Live no encontrada.", reply_markup=back_to_menu_keyboard())
            return

        res_live = await session.execute(select(Live).where(Live.id == inter.live_id))
        live = res_live.scalars().first()
        if not live:
            await query.edit_message_text("❌ Live asociado no encontrado.", reply_markup=back_to_menu_keyboard())
            return

        if query.from_user.id != live.telegram_id:
            await query.answer("No puedes rechazar esta interacción de Live.", show_alert=True)
            return
        if inter.status != "pending":
            await query.edit_message_text(f"⚠️ Esta interacción ya está en estado: {inter.status}.", reply_markup=back_to_menu_keyboard())
            return

        inter.status = "rejected"
        await session.commit()

    await query.edit_message_text("❌ Interacción de Live rechazada.", reply_markup=back_to_menu_keyboard())
    try:
        await notify_user(
            context,
            chat_id=inter.actor_id,
            text=f"❌ Tu apoyo al Live ({inter.tipo}) fue rechazado por el dueño."
        )
    except Exception as e:
        print("Aviso: no se pudo notificar al actor sobre el rechazo del Live:", e)

# bot.py (Parte 4/5)

# --- Mostrar balance e historial ---
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
        res_mov = await session.execute(
            select(Movimiento)
            .where(Movimiento.telegram_id == user_id)
            .order_by(Movimiento.created_at.desc())
            .limit(10)
        )
        movimientos = res_mov.scalars().all()

    if not user:
        texto = "❌ No estás registrado. Usa /start primero."
    else:
        texto = f"💰 Balance actual: {user.balance or 0} puntos\n\nÚltimos movimientos:\n"
        for mov in movimientos:
            texto += f"• {mov.detalle}: {mov.puntos} puntos ({mov.created_at})\n"

    reply_markup = back_to_menu_keyboard()
    if is_update:
        await update_or_query.message.reply_text(texto, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(texto, reply_markup=reply_markup)

# --- Listar usuarios ---
async def listar_usuarios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Solo el admin puede listar usuarios.", reply_markup=back_to_menu_keyboard())
        return
    async with async_session() as session:
        res = await session.execute(select(User))
        users = res.scalars().all()
    texto = "👥 Lista de usuarios:\n"
    for u in users:
        crown = "👑" if u.telegram_id == ADMIN_ID else ("👑" if getattr(u, "is_subadmin", False) else "")
        texto += f"{crown} ID {u.telegram_id} | Balance: {u.balance or 0} | TikTok: {u.tiktok_user or '-'}\n"
    await update.message.reply_text(texto, reply_markup=back_to_menu_keyboard())

# --- Gestión de subadmins ---
async def add_subadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Solo el admin puede agregar subadmins.", reply_markup=back_to_menu_keyboard())
        return
    if not context.args:
        await update.message.reply_text("Uso: /add_subadmin <telegram_id>", reply_markup=back_to_menu_keyboard())
        return
    try:
        sub_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ El ID debe ser numérico.", reply_markup=back_to_menu_keyboard())
        return

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == sub_id))
        u = res.scalars().first()
        if not u:
            await update.message.reply_text("❌ Usuario no encontrado.", reply_markup=back_to_menu_keyboard())
            return
        u.is_subadmin = True
        await session.commit()

    await update.message.reply_text(f"✅ Usuario {sub_id} promovido a subadmin.", reply_markup=back_to_menu_keyboard())
    await notify_user(context, chat_id=sub_id, text="🎉 Has sido promovido a subadmin.")

async def remove_subadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Solo el admin puede quitar subadmins.", reply_markup=back_to_menu_keyboard())
        return
    if not context.args:
        await update.message.reply_text("Uso: /remove_subadmin <telegram_id>", reply_markup=back_to_menu_keyboard())
        return
    try:
        sub_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ El ID debe ser numérico.", reply_markup=back_to_menu_keyboard())
        return

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == sub_id))
        u = res.scalars().first()
        if not u:
            await update.message.reply_text("❌ Usuario no encontrado.", reply_markup=back_to_menu_keyboard())
            return
        u.is_subadmin = False
        await session.commit()

    await update.message.reply_text(f"✅ Usuario {sub_id} ya no es subadmin.", reply_markup=back_to_menu_keyboard())

# --- Acciones administrativas propuestas ---
async def dar_puntos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Uso: /dar_puntos <telegram_id> <cantidad>", reply_markup=back_to_menu_keyboard())
        return
    try:
        target_id = int(context.args[0])
        cantidad = int(context.args[1])
    except ValueError:
        await update.message.reply_text("⚠️ ID y cantidad deben ser numéricos.", reply_markup=back_to_menu_keyboard())
        return

    actor_id = update.effective_user.id
    async with async_session() as session:
        if actor_id == ADMIN_ID:
            res_u = await session.execute(select(User).where(User.telegram_id == target_id))
            u = res_u.scalars().first()
            if not u:
                await update.message.reply_text("❌ Usuario objetivo no encontrado.", reply_markup=back_to_menu_keyboard())
                return
            u.balance = (u.balance or 0) + cantidad
            session.add(Movimiento(telegram_id=target_id, detalle="Puntos otorgados por admin", puntos=cantidad))
            await session.commit()
            await update.message.reply_text(f"✅ {cantidad} puntos otorgados a {target_id}.", reply_markup=back_to_menu_keyboard())
        else:
            # Subadmin propone
            action = AdminAction(
                tipo="dar_puntos",
                actor_id=actor_id,
                target_id=target_id,
                cantidad=cantidad,
                status="pending"
            )
            session.add(action)
            await session.commit()
            await update.message.reply_text("🟡 Acción propuesta, pendiente de aprobación del admin.", reply_markup=back_to_menu_keyboard())
            await notify_user(
                context,
                chat_id=ADMIN_ID,
                text=f"⚠️ Subadmin propone dar {cantidad} puntos a {target_id}.",
                reply_markup=yes_no_keyboard(
                    callback_yes=f"approve_admin_action_{action.id}",
                    callback_no=f"reject_admin_action_{action.id}"
                )
            )

async def cambiar_tiktok_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Uso: /cambiar_tiktok_usuario <telegram_id> <@usuario>", reply_markup=back_to_menu_keyboard())
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ El ID debe ser numérico.", reply_markup=back_to_menu_keyboard())
        return
    nuevo_alias = context.args[1]
    actor_id = update.effective_user.id

    async with async_session() as session:
        if actor_id == ADMIN_ID:
            res_u = await session.execute(select(User).where(User.telegram_id == target_id))
            u = res_u.scalars().first()
            if not u:
                await update.message.reply_text("❌ Usuario objetivo no encontrado.", reply_markup=back_to_menu_keyboard())
                return
            u.tiktok_user = nuevo_alias
            await session.commit()
            await update.message.reply_text(f"✅ Usuario TikTok de {target_id} cambiado a {nuevo_alias}.", reply_markup=back_to_menu_keyboard())
        else:
            action = AdminAction(
                tipo="cambiar_tiktok",
                actor_id=actor_id,
                target_id=target_id,
                nuevo_alias=nuevo_alias,
                status="pending"
            )
            session.add(action)
            await session.commit()
            await update.message.reply_text("🟡 Acción propuesta, pendiente de aprobación del admin.", reply_markup=back_to_menu_keyboard())
            await notify_user(
                context,
                chat_id=ADMIN_ID,
                text=f"⚠️ Subadmin propone cambiar TikTok de {target_id} a {nuevo_alias}.",
                reply_markup=yes_no_keyboard(
                    callback_yes=f"approve_admin_action_{action.id}",
                    callback_no=f"reject_admin_action_{action.id}"
                )
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
            if not u:
                await query.edit_message_text("❌ Usuario objetivo no encontrado.", reply_markup=back_to_menu_keyboard())
                return
            cantidad = action.cantidad or 0
            u.balance = (u.balance or 0) + cantidad
            session.add(Movimiento(
                telegram_id=u.telegram_id,
                detalle=f"Puntos otorgados por admin ({cantidad})",
                puntos=cantidad
            ))
        elif action.tipo == "cambiar_tiktok":
            res_u = await session.execute(select(User).where(User.telegram_id == action.target_id))
            u = res_u.scalars().first()
            if not u:
                await query.edit_message_text("❌ Usuario objetivo no encontrado.", reply_markup=back_to_menu_keyboard())
                return
            if action.nuevo_alias:
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

    elif data == "ver_live":
        await show_lives(query, context)

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

    elif data.startswith("live_view_done_"):
        live_id = int(data.split("_")[-1])
        await handle_live_interaction_done(query, context, live_id, tipo="view")

    elif data.startswith("live_gift_done_"):
        live_id = int(data.split("_")[-1])
        await handle_live_interaction_done(query, context, live_id, tipo="gift")

    elif data.startswith("approve_interaction_"):
        inter_id = int(data.split("_")[-1])
        await approve_interaction(query, context, inter_id)

    elif data.startswith("reject_interaction_"):
        inter_id = int(data.split("_")[-1])
        await reject_interaction(query, context, inter_id)

    elif data.startswith("approve_live_interaction_"):
        inter_id = int(data.split("_")[-1])
        await approve_live_interaction(query, context, inter_id)

    elif data.startswith("reject_live_interaction_"):
        inter_id = int(data.split("_")[-1])
        await reject_live_interaction(query, context, inter_id)

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
    elif state == "subir_live":
        await save_live(update, context)
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
        "• /listar_usuarios - Listar usuarios\n"
        "• /dar_puntos <id> <cantidad> - Proponer dar puntos (subadmin) o ejecutar (admin)\n"
        "• /cambiar_tiktok_usuario <id> <@usuario> - Proponer/ejecutar cambio de TikTok\n"
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
application.add_handler(CommandHandler("balance", show_balance))
application.add_handler(CommandHandler("listar_usuarios", listar_usuarios))
application.add_handler(CommandHandler("dar_puntos", dar_puntos))
application.add_handler(CommandHandler("cambiar_tiktok", cambiar_tiktok))
application.add_handler(CommandHandler("cambiar_tiktok_usuario", cambiar_tiktok_usuario))
application.add_handler(CommandHandler("add_subadmin", add_subadmin))
application.add_handler(CommandHandler("remove_subadmin", remove_subadmin))
application.add_handler(CommandHandler("mi_ref_link", cmd_my_ref_link))
application.add_handler(CommandHandler("comandos", comandos))
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

