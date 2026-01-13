# bot.py (Parte 1/3)

import os
import asyncio
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
    actor_id = Column(BigInteger)
    owner_id = Column(BigInteger)
    status = Column(Text, default="pending")
    puntos = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())
    __table_args__ = (UniqueConstraint("tipo", "item_id", "actor_id", name="uniq_tipo_item_actor"),)

# --- Inicialización DB ---
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Asegurar columnas críticas
        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='tiktok_user'
                ) THEN
                    ALTER TABLE users ADD COLUMN tiktok_user TEXT;
                END IF;
            END
            $$;
        """))

        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='balance'
                ) THEN
                    ALTER TABLE users ADD COLUMN balance INTEGER DEFAULT 10;
                END IF;
            END
            $$;
        """))

        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='interacciones' AND column_name='status'
                ) THEN
                    ALTER TABLE interacciones ADD COLUMN status TEXT DEFAULT 'pending';
                END IF;
            END
            $$;
        """))

# --- Config puntos ---
PUNTOS_APOYO_SEGUIMIENTO = 2
PUNTOS_APOYO_VIDEO = 3

# --- Canal de publicación ---
CHANNEL_ID = -1003468913370

# --- Configuración administrador ---
ADMIN_ID = 890166032  # tu Telegram ID aquí

def back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]]
    )
# bot.py (Parte 2/3)

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
    if isinstance(update_or_query, Update) and getattr(update_or_query, "message", None):
        await update_or_query.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(message, reply_markup=reply_markup)

# --- Start: se detiene en pedir usuario TikTok ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == update.effective_user.id))
        user = res.scalars().first()
        if not user:
            user = User(telegram_id=update.effective_user.id, balance=10)
            session.add(user)
            await session.commit()

        await update.message.reply_text(
            f"👋 Hola {update.effective_user.first_name}, bienvenido.\nTu balance actual es: {user.balance}",
            reply_markup=back_to_menu_keyboard()
        )
        await update.message.reply_text(
            "Por favor escribe tu usuario de TikTok para registrarte.",
            reply_markup=back_to_menu_keyboard()
        )
        context.user_data["state"] = "tiktok_user"

# --- Guardar usuario TikTok y mostrar menú ---
async def save_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text.strip()
    if not tiktok_user:
        await update.message.reply_text("⚠️ Envía un usuario válido.", reply_markup=back_to_menu_keyboard())
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

# --- Balance e historial (botón y comando) ---
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

# --- Ver seguimientos (no propios, solo una vez, envía mensaje nuevo) ---
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

# --- Ver videos (no propios, solo una vez, envía mensaje nuevo) ---
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

# --- Subir seguimiento (descuenta puntos y publica en canal) ---
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

    # Publicar en canal
    try:
        alias = user.tiktok_user if user and user.tiktok_user else str(user_id)
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📢 Nuevo seguimiento publicado por @{alias}\n🔗 {link}\n\n👉 No olvides seguir nuestro canal de noticias, cupones y promociones."
        )
    except Exception as e:
        print("Aviso: no se pudo publicar en el canal:", e)

# --- Flujo subir video: título, descripción, link, publica en canal ---
async def save_video_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["video_title"] = update.message.text.strip()
    context.user_data["state"] = "video_desc"
    await update.message.reply_text("📝 Ahora envíame la descripción del video:", reply_markup=back_to_menu_keyboard())

async def save_video_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["video_desc"] = update.message.text.strip()
    context.user_data["state"] = "video_link"
    await update.message.reply_text("🔗 Finalmente envíame el link del video de TikTok:", reply_markup=back_to_menu_keyboard())

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
            titulo=context.user_data.get("video_title"),
            descripcion=context.user_data.get("video_desc"),
            link=link
        )
        session.add(vid)
        user.balance = (user.balance or 0) - 5
        mov = Movimiento(telegram_id=user_id, detalle="Subir video", puntos=-5)
        session.add(mov)
        await session.commit()

    await update.message.reply_text("✅ Tu video se subió con éxito.", reply_markup=back_to_menu_keyboard())
    context.user_data["state"] = None

    # Publicar en canal
    try:
        alias = user.tiktok_user if user and user.tiktok_user else str(user_id)
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🎥 Nuevo video publicado por @{alias}\n📌 {context.user_data.get('video_title')}\n📝 {context.user_data.get('video_desc')}\n🔗 {link}\n\n👉 No olvides seguir nuestro canal de noticias, cupones y promociones."
        )
    except Exception as e:
        print("Aviso: no se pudo publicar en el canal:", e)
# bot.py (Parte 3/3)

# --- Reclamo de apoyo seguimiento ---
async def handle_seguimiento_done(query, context: ContextTypes.DEFAULT_TYPE, seg_id: int):
    actor_id = query.from_user.id
    async with async_session() as session:
        res = await session.execute(select(Seguimiento).where(Seguimiento.id == seg_id))
        seg = res.scalars().first()
        if not seg:
            await query.edit_message_text("❌ Seguimiento no disponible.", reply_markup=back_to_menu_keyboard())
            await show_main_menu(query, context)
            return
        owner_id = seg.telegram_id

        # Evitar duplicado del actor
        res = await session.execute(
            select(Interaccion).where(
                Interaccion.tipo == "seguimiento",
                Interaccion.item_id == seg_id,
                Interaccion.actor_id == actor_id
            )
        )
        exists = res.scalars().first()
        if exists:
            await query.edit_message_text(f"⚠️ Ya registraste apoyo para este seguimiento (estado: {exists.status}).", reply_markup=back_to_menu_keyboard())
            await show_main_menu(query, context)
            return

        inter = Interaccion(
            tipo="seguimiento",
            item_id=seg_id,
            actor_id=actor_id,
            owner_id=owner_id,
            status="pending",
            puntos=PUNTOS_APOYO_SEGUIMIENTO
        )
        session.add(inter)
        await session.commit()
        inter_id = inter.id

    await query.edit_message_text("🟡 Listo, se notificó al dueño para aprobación.", reply_markup=back_to_menu_keyboard())
    await show_main_menu(query, context)

    # Notificar al dueño
    try:
        async with async_session() as session:
            res = await session.execute(select(User.tiktok_user).where(User.telegram_id == actor_id))
            actor_tt = res.scalar()
        actor_tt = actor_tt if actor_tt else str(actor_id)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Aceptar", callback_data=f"approve_interaction_{inter_id}")],
            [InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_interaction_{inter_id}")],
            [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]
        ])
        await context.bot.send_message(
            chat_id=owner_id,
            text=f"📈 Solicitud: @{actor_tt} indica que ya siguió tu perfil.\nID: {inter_id}\n¿Aceptas otorgar {PUNTOS_APOYO_SEGUIMIENTO} puntos?",
            reply_markup=keyboard
        )
    except Exception as e:
        print("Aviso: no se pudo notificar al dueño del seguimiento:", e)

# --- Reclamo de apoyo video ---
async def handle_video_support_done(query, context: ContextTypes.DEFAULT_TYPE, vid_id: int):
    actor_id = query.from_user.id
    async with async_session() as session:
        res = await session.execute(select(Video).where(Video.id == vid_id))
        vid = res.scalars().first()
        if not vid:
            await query.edit_message_text("❌ Video no disponible.", reply_markup=back_to_menu_keyboard())
            await show_main_menu(query, context)
            return
        owner_id = vid.telegram_id

        res = await session.execute(
            select(Interaccion).where(
                Interaccion.tipo == "video_support",
                Interaccion.item_id == vid_id,
                Interaccion.actor_id == actor_id
            )
        )
        exists = res.scalars().first()
        if exists:
            await query.edit_message_text(f"⚠️ Ya registraste apoyo para este video (estado: {exists.status}).", reply_markup=back_to_menu_keyboard())
            await show_main_menu(query, context)
            return

        inter = Interaccion(
            tipo="video_support",
            item_id=vid_id,
            actor_id=actor_id,
            owner_id=owner_id,
            status="pending",
            puntos=PUNTOS_APOYO_VIDEO
        )
        session.add(inter)
        await session.commit()
        inter_id = inter.id

    await query.edit_message_text("🟡 Listo, se notificó al dueño para aprobación.", reply_markup=back_to_menu_keyboard())
    await show_main_menu(query, context)

    # Notificar al dueño
    try:
        async with async_session() as session:
            res = await session.execute(select(User.tiktok_user).where(User.telegram_id == actor_id))
            actor_tt = res.scalar()
        actor_tt = actor_tt if actor_tt else str(actor_id)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Aceptar", callback_data=f"approve_interaction_{inter_id}")],
            [InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_interaction_{inter_id}")],
            [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]
        ])
        await context.bot.send_message(
            chat_id=owner_id,
            text=f"🎥 Solicitud: @{actor_tt} apoyó tu video.\nID: {inter_id}\n¿Aceptas otorgar {PUNTOS_APOYO_VIDEO} puntos?",
            reply_markup=keyboard
        )
    except Exception as e:
        print("Aviso: no se pudo notificar al dueño del video:", e)

# --- Aprobar interacción (regresa al menú y actor con botón menú) ---
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
        await session.commit()

    await query.edit_message_text("✅ Interacción aprobada. Puntos otorgados.", reply_markup=back_to_menu_keyboard())
    await show_main_menu(query, context)
    try:
        keyboard = back_to_menu_keyboard()
        await context.bot.send_message(
            chat_id=inter.actor_id,
            text=f"✅ Tu apoyo en {inter.tipo} fue aprobado. Ganaste {inter.puntos} puntos.",
            reply_markup=keyboard
        )
    except Exception as e:
        print("Aviso: no se pudo notificar al actor:", e)

# --- Rechazar interacción (regresa al menú y actor con botón menú) ---
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
    try:
        keyboard = back_to_menu_keyboard()
        await context.bot.send_message(
            chat_id=inter.actor_id,
            text=f"❌ Tu apoyo en {inter.tipo} fue rechazado.",
            reply_markup=keyboard
        )
    except Exception as e:
        print("Aviso: no se pudo notificar al actor:", e)

# --- Comando exclusivo admin: /dar_puntos <usuario_id> <cantidad> ---
async def dar_puntos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No tienes permiso para usar este comando.")
        return

    try:
        args = context.args
        if len(args) != 2:
            await update.message.reply_text("Uso: /dar_puntos <usuario_id> <cantidad>")
            return
        target_id = int(args[0])
        cantidad = int(args[1])
    except:
        await update.message.reply_text("⚠️ Argumentos inválidos. Uso: /dar_puntos <usuario_id> <cantidad>")
        return

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == target_id))
        user = res.scalars().first()
        if not user:
            await update.message.reply_text("❌ Usuario no encontrado.")
            return
        user.balance = (user.balance or 0) + cantidad
        mov = Movimiento(telegram_id=target_id, detalle="Puntos otorgados por admin", puntos=cantidad)
        session.add(mov)
        await session.commit()

    await update.message.reply_text(f"✅ Se otorgaron {cantidad} puntos al usuario {target_id}.")
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"🎁 Has recibido {cantidad} puntos de administrador.",
            reply_markup=back_to_menu_keyboard()
        )
    except Exception as e:
        print("Aviso: no se pudo notificar al usuario:", e)

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

# --- Main ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")

application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("balance", cmd_balance))
application.add_handler(CommandHandler("dar_puntos", dar_puntos))
application.add_handler(CallbackQueryHandler(menu_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

# --- Flask Webhook ---
flask_app = Flask(__name__)

@flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "ok"

@flask_app.route("/")
def home():
    return "Bot de Telegram corriendo con Webhook en Render!"

# --- Run ---
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        url_path=BOT_TOKEN,
        webhook_url=f"https://{RENDER_EXTERNAL_HOSTNAME}/{BOT_TOKEN}"
    )
    