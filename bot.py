# -*- coding: utf-8 -*-
# =====================================================================
# 📋 BOT DE APOYO MUTUO - LORD NOLIK (EDICIÓN SUPREMA)
# 🔹 ARCHIVO: bot.py | PARTE 1: Infraestructura
# =====================================================================

import os
import asyncio
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ConversationHandler
)
from telegram.request import HTTPXRequest

# 🗄️ LIBRERÍAS DE BASE DE DATOS
from sqlalchemy import Column, Integer, BigInteger, String, Text, text, UniqueConstraint, DateTime, Boolean
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

# =====================================================================
# ⚙️ CREDENCIALES Y CONFIGURACIÓN (TUS DATOS)
# =====================================================================
TOKEN = "6564290496:AAFfyjhNUHMQaryJgMxK-gBNGkJX41Cay0A"
DATABASE_URL = "postgresql+asyncpg://base1_ufc1_user:GJ1zrLRgzKzGepMpHzsYBPrvPm8hcAus@dpg-d82gkghj2pic73ah6m70-a/base1_ufc1"

# 💰 VARIABLES DE ECONOMÍA (Importante para que no falle el Status 1)
COSTO_VIDEO = 5
PUNTOS_POR_VIDEO = 3

# =====================================================================
# 🗄️ MODELOS DE LAS TABLAS (ESTRUCTURA POSTGRESQL)
# =====================================================================
Base = declarative_base()


class Usuario(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    tiktok_user = Column(String(100), unique=True, nullable=True)
    balance = Column(Integer, default=10)
    es_vip = Column(Boolean, default=False)
    # admin, subadmin, vip, usuario
    rol = Column(String(30), default="usuario")
    contador_ingresos = Column(Integer, default=1)
    referido_por = Column(BigInteger, nullable=True)
    contacto_vip = Column(String(255), nullable=True)
    porcentaje_regalo_vip = Column(Integer, default=0)
    creado_at = Column(DateTime, default=datetime.utcnow)


class Movimiento(Base):
    __tablename__ = "movimientos"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=False)
    detalle = Column(String(255), nullable=False)
    puntos = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CampanaVideo(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=False)
    tipo = Column(String(50))
    titulo = Column(String(150))
    descripcion = Column(Text)
    link = Column(Text)
    es_propio = Column(Boolean, default=True)
    meta_apoyo = Column(String(50))
    file_id_flyer = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Interaccion(Base):
    __tablename__ = "interacciones"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tipo = Column(String(50))
    item_id = Column(Integer)
    actor_id = Column(BigInteger)
    owner_id = Column(BigInteger)
    status = Column(String(30), default="pending")
    puntos = Column(Integer)
    file_id_evidencia = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('tipo', 'item_id',
                      'actor_id', name='uix_interaccion'),)


# =====================================================================
# 🚀 MOTOR ASÍNCRONO
# =====================================================================
engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False)


async def inicializar_base_de_datos():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Base de datos conectada.")
    # =====================================================================
# 📋 BOT DE APOYO MUTUO - LORD NOLIK
# 🔹 BLOQUE EN CURSO: PARTE 2 (Seguridad, Registro y Filtros de Comunidad)
# =====================================================================

# Configura aquí tus IDs reales de Telegram (Canal y Grupos)
ID_CANAL_OFICIAL = "@TuCanalOficial"  # Cambia por el tuyo
ID_GRUPO_1 = -1001234567890         # Cambia por la ID real
ID_GRUPO_2 = -1000987654321         # Cambia por la ID real


async def es_miembro_comunidad(bot, user_id):
    """ Verifica si el usuario está en el canal y los 2 grupos obligatorios """
    for chat in [ID_CANAL_OFICIAL, ID_GRUPO_1, ID_GRUPO_2]:
        try:
            member = await bot.get_chat_member(chat_id=chat, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        except Exception:
            return False
    return True

# --- INICIO DEL COMANDO /START ---


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tg_id = user.id
    first_name = user.first_name

    # 🔗 Captura de Referido Invisible (/start?startapp=ID)
    id_patrocinador = None
    if context.args:
        arg = context.args[0]
        if arg.isdigit() and int(arg) != tg_id:
            id_patrocinador = int(arg)

    async with AsyncSessionLocal() as session:
        # 1. Buscar si el usuario ya existe
        res = await session.execute(text("SELECT tiktok_user, contador_ingresos, rol FROM users WHERE telegram_id = :tid"), {"tid": tg_id})
        usuario_db = res.fetchone()

        if not usuario_db:
            # 🆕 USUARIO NUEVO: Registro inicial
            await session.execute(
                text(
                    "INSERT INTO users (telegram_id, balance, referido_por, contador_ingresos) VALUES (:tid, 10, :ref, 1)"),
                {"tid": tg_id, "ref": id_patrocinador}
            )
            await session.commit()

            # Saludo de bienvenida y Filtro 1: Registro TikTok
            await update.message.reply_text(
                f"👋 ¡Hola **{first_name}**! Bienvenido a la plataforma de apoyo mutuo para videos, Lives y eventos.\n\n"
                "⚠️ **FILTRO DE SEGURIDAD 1:**\n"
                "Para evitar cuentas falsas, por favor escribe tu **usuario de TikTok** (sin @ y sin espacios):",
                parse_mode="Markdown"
            )
            context.user_data["esperando_tiktok"] = True
            return
        else:
            # 🔄 USUARIO EXISTENTE: Sumar ingreso
            nuevo_conteo = usuario_db[1] + 1
            await session.execute(text("UPDATE users SET contador_ingresos = :c WHERE telegram_id = :tid"), {"c": nuevo_conteo, "tid": tg_id})
            await session.commit()

            # Verificar si tiene el TikTok registrado
            if not usuario_db[0]:
                await update.message.reply_text("⚠️ Aún no registras tu TikTok. Por favor, escríbelo:")
                context.user_data["esperando_tiktok"] = True
                return

            # Filtro 2: Verificación de Comunidad (Canal y Grupos)
            if not await es_miembro_comunidad(context.bot, tg_id):
                botones = [
                    [InlineKeyboardButton(
                        "📢 Canal Oficial", url=f"https://t.me/{ID_CANAL_OFICIAL.replace('@','')}")],
                    [InlineKeyboardButton(
                        "👥 Grupo de Apoyo 1", url="https://t.me/LinkGrupo1")],
                    [InlineKeyboardButton(
                        "👥 Grupo de Apoyo 2", url="https://t.me/LinkGrupo2")],
                    [InlineKeyboardButton(
                        "🔄 ¡Ya me uní! Verificar", callback_data="verificar_union")]
                ]
                await update.message.reply_text(
                    f"🛡️ **{first_name}**, para activar el bot debes seguir nuestro canal y los 2 grupos de apoyo:",
                    reply_markup=InlineKeyboardMarkup(botones),
                    parse_mode="Markdown"
                )
                return

            # Si pasa todo, enviar al Menú Principal (Se define en la Parte 3)
            await enviar_menu_principal(update, context, tg_id)

# --- MANEJADOR DE TEXTO (Para el TikTok y Capturas) ---


async def manejador_mensajes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    texto = update.message.text.strip().replace("@", "")

    # Procesar registro de TikTok
    if context.user_data.get("esperando_tiktok"):
        async with AsyncSessionLocal() as session:
            # Validar unicidad (Filtro Anti-Fraude)
            check = await session.execute(text("SELECT telegram_id FROM users WHERE tiktok_user = :tk"), {"tk": texto})
            if check.fetchone():
                await update.message.reply_text("❌ Este usuario de TikTok ya está registrado con otra cuenta de Telegram. Usa uno real.")
                return

            await session.execute(text("UPDATE users SET tiktok_user = :tk WHERE telegram_id = :tid"), {"tk": texto, "tid": tg_id})
            await session.commit()

        context.user_data["esperando_tiktok"] = False
        await update.message.reply_text(f"✅ ¡TikTok `@{texto}` registrado con éxito!")
        await start(update, context)  # Re-lanzar para verificar comunidad

        # =====================================================================
# 📋 BOT DE APOYO MUTUO - LORD NOLIK
# 🔹 BLOQUE EN CURSO: PARTE 3 (Menú Principal, Billetera e Historial)
# =====================================================================


async def enviar_menu_principal(update, context, tg_id):
    """ Genera el menú táctil según el rango del usuario (Admin, VIP, Regular) """
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            text("SELECT balance, es_vip, rol, tiktok_user, contador_ingresos FROM users WHERE telegram_id = :tid"),
            {"tid": tg_id}
        )
        user_db = res.fetchone()
        balance, es_vip, rol, tk_user, visitas = user_db

    # Personalización estética
    corona = "⭐ " if es_vip else ""
    rango_txt = rol.upper()

    mensaje = (
        f"📱 **PANEL DE CONTROL {corona}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Usuario:** `@{tk_user}`\n"
        f"🎖️ **Rango:** `{rango_txt}`\n"
        f"💰 **Saldo:** `{balance}` Nolik Coins\n"
        f"📈 **Visitas al Bot:** `{visitas}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        "Selecciona una opción del menú:"
    )

    # Botones Base
    botones = [
        [InlineKeyboardButton(
            "➕ Publicar Campaña (Video/Live)", callback_data="crear_campana")],
        [InlineKeyboardButton("👀 Tareas Disponibles",
                              callback_data="ver_tareas")],
        [InlineKeyboardButton("💰 Mi Billetera e Historial",
                              callback_data="ver_billetera")],
        [InlineKeyboardButton(
            "🔗 Mis Referidos", callback_data="ver_referidos")]
    ]

    # Botones Exclusivos VIP
    if es_vip:
        botones.insert(2, [InlineKeyboardButton(
            "⚙️ Configuración VIP (Regalos/Contacto)", callback_data="config_vip")])

    # Botones Exclusivos ADMIN / SUBADMIN
    if rol in ["admin", "subadmin"]:
        botones.append([InlineKeyboardButton(
            "🛠️ Panel de Soporte / Admin", callback_data="panel_admin")])

    # Responder si es mensaje nuevo o edición (callback)
    if update.callback_query:
        await update.callback_query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(botones), parse_mode="Markdown")
    else:
        await update.message.reply_text(mensaje, reply_markup=InlineKeyboardMarkup(botones), parse_mode="Markdown")

# --- LÓGICA DE LA BILLETERA (ÚLTIMOS 5 MOVIMIENTOS) ---


async def mostrar_billetera(query, tg_id):
    async with AsyncSessionLocal() as session:
        # 1. Obtener saldo actual
        res_user = await session.execute(text("SELECT balance FROM users WHERE telegram_id = :tid"), {"tid": tg_id})
        balance = res_user.scalar()

        # 2. Obtener últimos 5 movimientos
        res_movs = await session.execute(
            text("SELECT detalle, puntos, created_at FROM movimientos WHERE telegram_id = :tid ORDER BY created_at DESC LIMIT 5"),
            {"tid": tg_id}
        )
        movimientos = res_movs.fetchall()

    historial_txt = ""
    if not movimientos:
        historial_txt = "_No hay transacciones recientes._"
    else:
        for m in movimientos:
            simbolo = "🟢" if m[1] > 0 else "🔴"
            fecha = m[2].strftime("%d/%m/%Y %H:%M")
            historial_txt += f"{simbolo} `{m[1]}` | {m[0]} | _{fecha}_\n"

    mensaje_bill = (
        "💰 **MI BILLETERA E HISTORIAL**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💵 **Saldo Total:** `{balance}` Nolik Coins\n\n"
        "📋 **Últimos 5 Movimientos:**\n"
        f"{historial_txt}\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    botones = [[InlineKeyboardButton(
        "🔙 Regresar al Menú", callback_data="volver_menu")]]
    await query.edit_message_text(mensaje_bill, reply_markup=InlineKeyboardMarkup(botones), parse_mode="Markdown")

# --- MANEJADOR DE CALLBACKS (BOTONES) ---


async def manejador_botones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tg_id = update.effective_user.id
    data = query.data

    if data == "ver_billetera":
        await mostrar_billetera(query, tg_id)

    elif data == "volver_menu":
        await enviar_menu_principal(update, context, tg_id)

    elif data == "verificar_union":
        # Re-verifica si ya se unió a los grupos
        if await es_miembro_comunidad(context.bot, tg_id):
            await enviar_menu_principal(update, context, tg_id)
        else:
            await query.answer("❌ Aún no te has unido a todos los grupos.", show_alert=True)

    elif data == "ver_referidos":
        link = f"https://t.me/{(await context.bot.get_me()).username}?startapp={tg_id}"
        async with AsyncSessionLocal() as session:
            res = await session.execute(text("SELECT COUNT(*) FROM users WHERE referido_por = :tid"), {"tid": tg_id})
            total_ref = res.scalar()

        txt_ref = (
            "🔗 **SISTEMA DE REFERIDOS**\n\n"
            f"Tu link de invitación:\n`{link}`\n\n"
            f"👥 **Invitados totales:** `{total_ref}`\n"
            "🎁 *Ganas el 10% de lo que ellos generen (20% si eres VIP).*"
        )
        await query.edit_message_text(txt_ref, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver", callback_data="volver_menu")]]), parse_mode="Markdown")
        # =====================================================================
# 📋 BOT DE APOYO MUTUO - LORD NOLIK
# 🔹 BLOQUE EN CURSO: PARTE 4 (Creación de Campañas y Filtros de Video)
# =====================================================================

# Estados para la creación de campaña
CATEGORIA, PROPIEDAD, TIPO_APOYO, LINK_VIDEO, FLYER = range(5)


async def iniciar_creacion_campana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tg_id = update.effective_user.id

    async with AsyncSessionLocal() as session:
        res = await session.execute(text("SELECT balance FROM users WHERE telegram_id = :tid"), {"tid": tg_id})
        balance = res.scalar()

    if balance < COSTO_VIDEO:
        await query.answer(f"❌ Saldo insuficiente. Necesitas {COSTO_VIDEO} Nolik Coins.", show_alert=True)
        return

    botones = [
        [InlineKeyboardButton("📹 Normal", callback_query="cat_normal"), InlineKeyboardButton(
            "🛍️ TikTok Shop", callback_data="cat_shop")],
        [InlineKeyboardButton("🔥 Incentivo Live", callback_data="cat_live"), InlineKeyboardButton(
            "⚔️ Batalla/Evento", callback_data="cat_evento")],
        [InlineKeyboardButton("🔙 Cancelar", callback_data="volver_menu")]
    ]

    await query.edit_message_text(
        "🎬 **NUEVA CAMPAÑA**\n\nSelecciona la categoría de tu video:",
        reply_markup=InlineKeyboardMarkup(botones),
        parse_mode="Markdown"
    )
    return CATEGORIA


async def seleccion_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["campana_cat"] = query.data.replace("cat_", "")

    botones = [
        [InlineKeyboardButton("👤 Es mío", callback_data="prop_si"), InlineKeyboardButton(
            "👥 Es de un tercero", callback_data="prop_no")],
        [InlineKeyboardButton("🔙 Regresar al Menú",
                              callback_data="volver_menu")]
    ]
    await query.edit_message_text("❓ **¿El video es tuyo o de alguien más?**", reply_markup=InlineKeyboardMarkup(botones))
    return PROPIEDAD


async def seleccion_propiedad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["campana_prop"] = True if query.data == "prop_si" else False

    botones = [
        [InlineKeyboardButton("👁️ Solo Vistas", callback_data="apoyo_vistas")],
        [InlineKeyboardButton("✅ Completo (Like+Guardar+Comp)",
                              callback_data="apoyo_completo")],
        [InlineKeyboardButton("🔙 Regresar al Menú",
                              callback_data="volver_menu")]
    ]
    await query.edit_message_text("🎯 **¿Qué tipo de apoyo necesitas?**", reply_markup=InlineKeyboardMarkup(botones))
    return TIPO_APOYO


async def seleccion_apoyo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data["campana_apoyo"] = query.data.replace("apoyo_", "")

    await query.edit_message_text(
        "🔗 **Pega el link de tu video de TikTok:**\n\n"
        "_(Asegúrate de que sea el link directo)_",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Cancelar", callback_data="volver_menu")]])
    )
    return LINK_VIDEO


async def recibir_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if "tiktok.com" not in link:
        await update.message.reply_text("❌ Link inválido. Por favor envía un enlace real de TikTok.")
        return LINK_VIDEO

    context.user_data["campana_link"] = link

    botones = [[InlineKeyboardButton(
        "⏩ Omitir y Publicar", callback_data="omitir_flyer")]]
    await update.message.reply_text(
        "🖼️ **VISTA PREVIA (Opcional)**\n\nEnvía una imagen o Flyer promocional para tu campaña, o presiona omitir:",
        reply_markup=InlineKeyboardMarkup(botones)
    )
    return FLYER


async def finalizar_campana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    flyer_id = None

    # Si envió foto
    if update.message and update.message.photo:
        flyer_id = update.message.photo[-1].file_id

    # Guardar en Base de Datos de Render
    async with AsyncSessionLocal() as session:
        # Descontar saldo
        await session.execute(
            text("UPDATE users SET balance = balance - :costo WHERE telegram_id = :tid"),
            {"costo": COSTO_VIDEO, "tid": tg_id}
        )
        # Registrar movimiento
        await session.execute(
            text(
                "INSERT INTO movimientos (telegram_id, detalle, puntos) VALUES (:tid, :det, :pts)"),
            {"tid": tg_id,
                "det": f"Publicación video {context.user_data['campana_cat']}", "pts": -COSTO_VIDEO}
        )
        # Insertar campaña
        await session.execute(
            text("INSERT INTO videos (telegram_id, tipo, titulo, link, es_propio, meta_apoyo, file_id_flyer) "
                 "VALUES (:tid, :tipo, :tit, :link, :prop, :meta, :flyer)"),
            {
                "tid": tg_id, "tipo": context.user_data['campana_cat'], "tit": "Campaña Lord Nolik",
                "link": context.user_data['campana_link'], "prop": context.user_data['campana_prop'],
                "meta": context.user_data['campana_apoyo'], "flyer": flyer_id
            }
        )
        await session.commit()

    await update.message.reply_text("🚀 **¡Campaña publicada con éxito!**\nYa está disponible para que la comunidad te apoye.")
    context.user_data.clear()
    await enviar_menu_principal(update, context, tg_id)
    return ConversationHandler.END

# =====================================================================
# 📋 BOT DE APOYO MUTUO - LORD NOLIK
# 🔹 BLOQUE EN CURSO: PARTE 5 (Distribución de Tareas y Validación WebApp)
# =====================================================================

# Configuración de recompensas
PUNTOS_POR_VIDEO = 3


async def ver_tareas_disponibles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tg_id = update.effective_user.id

    async with AsyncSessionLocal() as session:
        # Buscamos videos que NO sean del usuario y que NO haya hecho ya
        res = await session.execute(
            text("""
                SELECT v.id, v.tipo, v.link, v.file_id_flyer, v.meta_apoyo 
                FROM videos v 
                WHERE v.telegram_id != :tid 
                AND v.id NOT IN (SELECT item_id FROM interacciones WHERE actor_id = :tid AND tipo = 'video')
                ORDER BY v.created_at DESC LIMIT 1
            """), {"tid": tg_id}
        )
        tarea = res.fetchone()

    if not tarea:
        await query.answer("📭 No hay tareas nuevas por ahora. ¡Vuelve más tarde!", show_alert=True)
        return

    v_id, v_tipo, v_link, v_flyer, v_meta = tarea

    # Construcción del mensaje de tarea
    txt_tarea = (
        f"📺 **NUEVA TAREA DISPONIBLE**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ **Categoría:** `{v_tipo.upper()}`\n"
        f"🎯 **Meta:** `{v_meta.upper()}`\n"
        f"💰 **Recompensa:** `{PUNTOS_POR_VIDEO}` Nolik Coins\n\n"
        f"⚠️ **INSTRUCCIONES:**\n"
        f"1. Abre el video con el botón de abajo.\n"
        f"2. Espera que el contador llegue a cero.\n"
        f"3. Toma captura y envíala aquí."
    )

    # Botón con WebApp para el Contador (Simulado con URL externa o WebApp propia)
    # Aquí Lord Nolik, el link de la WebApp debe apuntar a tu servidor de Render con el timer.
    url_web_timer = f"https://tu-app-en-render.com/timer?id={v_id}&link={v_link}"

    botones = [
        [InlineKeyboardButton("🔗 Ver Video (Contador)",
                              web_app=WebAppInfo(url=url_web_timer))],
        [InlineKeyboardButton("⏭️ Saltar", callback_data="ver_tareas")],
        [InlineKeyboardButton("🔙 Menú Principal", callback_data="volver_menu")]
    ]

    if v_flyer:
        await context.bot.send_photo(
            chat_id=tg_id, photo=v_flyer, caption=txt_tarea,
            reply_markup=InlineKeyboardMarkup(botones), parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(txt_tarea, reply_markup=InlineKeyboardMarkup(botones), parse_mode="Markdown")

    # Guardamos en qué tarea está el usuario
    context.user_data["tarea_activa"] = v_id

# --- SENSOR DE FOTOS (EVIDENCIA DE TAREA) ---


async def recibir_evidencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id

    if "tarea_activa" not in context.user_data:
        return  # No está haciendo tarea

    v_id = context.user_data["tarea_activa"]
    foto_id = update.message.photo[-1].file_id

    async with AsyncSessionLocal() as session:
        # Obtener quién es el dueño del video
        res_v = await session.execute(text("SELECT telegram_id FROM videos WHERE id = :vid"), {"vid": v_id})
        owner_id = res_v.scalar()

        # Registrar la interacción como PENDIENTE
        try:
            await session.execute(
                text("""
                    INSERT INTO interacciones (tipo, item_id, actor_id, owner_id, status, file_id_evidencia, puntos)
                    VALUES ('video', :vid, :aid, :oid, 'pending', :fid, :pts)
                """),
                {"vid": v_id, "aid": tg_id, "oid": owner_id,
                    "fid": foto_id, "pts": PUNTOS_POR_VIDEO}
            )
            await session.commit()
        except Exception:
            await update.message.reply_text("❌ Ya habías enviado evidencia para este video.")
            return

    # Notificar al dueño para que Apruebe o Rechace
    botones_admin = [
        [
            InlineKeyboardButton(
                "✅ Aprobar", callback_data=f"aprobar_{tg_id}_{v_id}"),
            InlineKeyboardButton(
                "❌ Rechazar", callback_data=f"rechazar_{tg_id}_{v_id}")
        ]
    ]

    await context.bot.send_photo(
        chat_id=owner_id,
        photo=foto_id,
        caption=f"📩 **NUEVA EVIDENCIA RECIBIDA**\nEl usuario `{tg_id}` dice haber completado tu tarea.\n¿Es correcto?",
        reply_markup=InlineKeyboardMarkup(botones_admin),
        parse_mode="Markdown"
    )

    await update.message.reply_text("✅ **Evidencia enviada.**\nEsperando a que el dueño valide tu apoyo para liberar tus puntos.")
    context.user_data.pop("tarea_activa")
    # =====================================================================
# 📋 BOT DE APOYO MUTUO - LORD NOLIK
# 🔹 BLOQUE EN CURSO: PARTE 6 (Panel Admin, Cupones y Nómina Staff)
# =====================================================================


async def panel_administracion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tg_id = update.effective_user.id

    async with AsyncSessionLocal() as session:
        res = await session.execute(text("SELECT rol FROM users WHERE telegram_id = :tid"), {"tid": tg_id})
        rol = res.scalar()

    if rol not in ["admin", "subadmin"]:
        await query.answer("🚫 Acceso denegado.", show_alert=True)
        return

    txt = (
        "🛠️ **PANEL DE CONTROL ADMINISTRATIVO**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Desde aquí puedes gestionar la economía y el soporte del sistema.\n"
        "Recuerda: Todas las acciones quedan registradas."
    )

    botones = [
        [InlineKeyboardButton("🎫 Crear Cupón (Ej. Luis5)",
                              callback_data="admin_crear_cupon")],
        [InlineKeyboardButton("📥 Respaldo de Base de Datos",
                              callback_data="admin_backup")],
        [InlineKeyboardButton("👥 Buscar Usuario / Ver Capturas",
                              callback_data="admin_buscar_user")],
        [InlineKeyboardButton("🔙 Volver al Menú", callback_data="volver_menu")]
    ]

    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(botones), parse_mode="Markdown")

# --- MOTOR DE CUPONES (REGLA MATEMÁTICA) ---
# Formato: /cupon CODIGO PUNTOS_TOTALES CANTIDAD_PERSONAS


async def crear_cupon_comando(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id

    async with AsyncSessionLocal() as session:
        res = await session.execute(text("SELECT rol FROM users WHERE telegram_id = :tid"), {"tid": tg_id})
        if res.scalar() != "admin":
            return  # Solo el Supremo

    try:
        codigo = context.args[0]
        pts_totales = int(context.args[1])
        personas = int(context.args[2])

        # Lógica matemática: pts_por_persona = totales / personas
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "INSERT INTO cupones (codigo, puntos_totales, cantidad_personas) VALUES (:c, :p, :n)"),
                {"c": codigo, "p": pts_totales, "n": personas}
            )
            await session.commit()

        await update.message.reply_text(
            f"✅ **Cupón Creado:** `{codigo}`\n"
            f"💰 **Total:** `{pts_totales}` coins\n"
            f"👥 **Límite:** `{personas}` personas\n"
            f"🎁 **Cada uno recibe:** `{pts_totales // personas}` coins."
        )
    except:
        await update.message.reply_text("❌ Uso: `/cupon Luis5 100 100` (Nombre, Puntos, Personas)")

# --- SISTEMA DE NÓMINA AUTOMÁTICA (CADA 30 DÍAS) ---


async def ejecutar_nomina_staff(context: ContextTypes.DEFAULT_TYPE):
    """ Función que corre en background para pagar 150 coins al staff """
    async with AsyncSessionLocal() as session:
        # Pagar a Admins y Subadmins
        await session.execute(
            text("""
                UPDATE users SET balance = balance + 150 
                WHERE rol IN ('admin', 'subadmin')
            """)
        )
        # Registrar el movimiento para el historial de ellos
        res = await session.execute(text("SELECT telegram_id FROM users WHERE rol IN ('admin', 'subadmin')"))
        staff_ids = res.fetchall()

        for s_id in staff_ids:
            await session.execute(
                text("INSERT INTO movimientos (telegram_id, detalle, puntos) VALUES (:tid, 'Pago de Nómina Mensual Staff', 150)"),
                {"tid": s_id[0]}
            )
        await session.commit()
    print("💸 Nómina de Staff pagada exitosamente.")

# --- SOPORTE: APROBACIÓN DE SUBADMINS CON DESVÍO AL SUPREMO ---


async def procesar_aprobacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data  # "aprobar_IDUSER_IDVIDEO"
    _, actor_id, video_id = data.split("_")

    # Aquí Lord Nolik, si el que aprueba es SUBADMIN, le mandamos el botón a ti
    # Pero para esta versión base, el dueño del video aprueba directo:
    async with AsyncSessionLocal() as session:
        # 1. Actualizar interacción
        await session.execute(
            text("UPDATE interacciones SET status = 'completed' WHERE actor_id = :aid AND item_id = :vid"),
            {"aid": int(actor_id), "vid": int(video_id)}
        )
        # 2. Pagar puntos al trabajador
        await session.execute(
            text("UPDATE users SET balance = balance + :pts WHERE telegram_id = :aid"),
            {"pts": PUNTOS_POR_VIDEO, "aid": int(actor_id)}
        )
        # 3. Registrar movimiento
        await session.execute(
            text("INSERT INTO movimientos (telegram_id, detalle, puntos) VALUES (:tid, 'Tarea Video Completada', :pts)"),
            {"tid": int(actor_id), "pts": PUNTOS_POR_VIDEO}
        )
        await session.commit()

    await query.edit_message_caption("✅ Tarea aprobada y puntos enviados.")
    await context.bot.send_message(chat_id=int(actor_id), text=f"🎉 ¡Tu evidencia fue aprobada! Recibiste `{PUNTOS_POR_VIDEO}` Nolik Coins.")
    # =====================================================================
# 📋 BOT DE APOYO MUTUO - LORD NOLIK
# 🔹 BLOQUE EN CURSO: PARTE 7 (Ecosistema VIP y Rescate de Datos)
# =====================================================================


async def menu_config_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tg_id = update.effective_user.id

    async with AsyncSessionLocal() as session:
        res = await session.execute(
            text(
                "SELECT porcentaje_regalo_vip, contacto_vip FROM users WHERE telegram_id = :tid"),
            {"tid": tg_id}
        )
        vip_data = res.fetchone()

    porcentaje, contacto = vip_data
    contacto_status = contacto if contacto else "❌ No configurado"

    txt = (
        "⭐ **PANEL DE CONFIGURACIÓN VIP**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📊 **Regalo actual:** `{porcentaje}%` de tus ganancias.\n"
        f"📱 **Contacto:** `{contacto_status}`\n\n"
        "Configura qué porcentaje de tus Nolik Coins regalarás a tu comunidad en tus dinámicas:"
    )

    botones = [
        [
            InlineKeyboardButton("5%", callback_data="setvip_5"),
            InlineKeyboardButton("10%", callback_data="setvip_10"),
            InlineKeyboardButton("15%", callback_data="setvip_15"),
            InlineKeyboardButton("50%", callback_data="setvip_50")
        ],
        [InlineKeyboardButton("📱 Cambiar Link de Contacto",
                              callback_data="setvip_contacto")],
        [InlineKeyboardButton("🔙 Volver al Menú", callback_data="volver_menu")]
    ]

    await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(botones), parse_mode="Markdown")

# --- PROCESADOR DE CAMBIOS VIP ---


async def procesar_cambios_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tg_id = update.effective_user.id
    data = query.data

    if "setvip_" in data and "contacto" not in data:
        nuevo_porcentaje = int(data.split("_")[1])
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "UPDATE users SET porcentaje_regalo_vip = :p WHERE telegram_id = :tid"),
                {"p": nuevo_porcentaje, "tid": tg_id}
            )
            await session.commit()
        await query.answer(f"✅ Ahora regalarás el {nuevo_porcentaje}%", show_alert=True)
        await menu_config_vip(update, context)

    elif data == "setvip_contacto":
        await query.edit_message_text("📝 Envía tu link de WhatsApp o Telegram para que tus seguidores te contacten:")
        context.user_data["esperando_contacto_vip"] = True

# --- BOTÓN DE RESCATE (BACKUP SUPREMO) ---


async def exportar_base_datos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    tg_id = update.effective_user.id

    async with AsyncSessionLocal() as session:
        # Verificar que solo tú (Admin) puedas hacerlo
        res = await session.execute(text("SELECT rol FROM users WHERE telegram_id = :tid"), {"tid": tg_id})
        if res.scalar() != "admin":
            await query.answer("🚫 Solo Lord Nolik puede rescatar la base de datos.", show_alert=True)
            return

        # Extraer todo (Usuarios y Movimientos)
        res_users = await session.execute(text("SELECT * FROM users"))
        users_list = [dict(r._mapping) for r in res_users.fetchall()]

        # Convertir fechas a string para el JSON
        for u in users_list:
            u['creado_at'] = str(u['creado_at'])

        backup_data = {
            "fecha_rescate": str(datetime.now()),
            "usuarios": users_list
        }

        # Generar archivo físico
        file_path = f"rescate_nolik_{datetime.now().strftime('%d_%m_%Y')}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, indent=4, ensure_ascii=False)

        # Enviar por Telegram
        await context.bot.send_document(
            chat_id=tg_id,
            document=open(file_path, "rb"),
            caption="📦 **RESCATE DE BASE DE DATOS COMPLETADO**\nGuarda este archivo. Contiene todos tus usuarios y saldos."
        )
        os.remove(file_path)  # Limpiar archivo del servidor de Render
        # =====================================================================
# 📋 BOT DE APOYO MUTUO - LORD NOLIK
# 🔹 BLOQUE FINAL: PARTE 8 (Configuración Webhook para Render)
# =====================================================================


# --- CONFIGURACIÓN DE RENDER ---
# La URL de tu servicio en Render (Ej: https://tu-bot.onrender.com)
URL_WEBHOOK_RENDER = "https://tu-proyecto-en-render.onrender.com"
PORT = int(os.environ.get("PORT", 8080))


async def handle_webhook(request):
    """ Recibe las actualizaciones de Telegram vía Webhook """
    app_bot = request.app['bot_app']
    body = await request.json()
    update = Update.de_json(body, app_bot.bot)
    await app_bot.process_update(update)
    return web.Response(status=200)


async def handle_health_check(request):
    """ Página simple para que Render sepa que el bot está vivo """
    return web.Response(text="🚀 Lord Nolik Bot está operando mediante Webhook.")


async def on_startup(app_web):
    """ Configura el webhook en los servidores de Telegram al arrancar """
    app_bot = app_web['bot_app']
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.bot.set_webhook(url=f"{URL_WEBHOOK_RENDER}/{TOKEN}")
    print(f"✅ Webhook configurado en: {URL_WEBHOOK_RENDER}")


async def on_cleanup(app_web):
    """ Apaga el bot correctamente """
    app_bot = app_web['bot_app']
    await app_bot.stop()
    await app_bot.shutdown()

# --- MANEJADOR DE ERRORES ---


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"⚠️ Error detectado: {context.error}")

# --- ARRANQUE MAESTRO ---


def main():
    # 1. Configurar Tiempos de Espera
    request_config = HTTPXRequest(connect_timeout=20.0, read_timeout=30.0)

    # 2. Construir la Aplicación del Bot
    application = (
        Application.builder()
        .token(TOKEN)
        .request(request_config)
        .build()
    )

    # 3. Registrar Handlers (Mantenemos los mismos de antes)
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(
            iniciar_creacion_campana, pattern="^crear_campana$")],
        states={
            CATEGORIA: [CallbackQueryHandler(seleccion_categoria, pattern="^cat_")],
            PROPIEDAD: [CallbackQueryHandler(seleccion_propiedad, pattern="^prop_")],
            TIPO_APOYO: [CallbackQueryHandler(seleccion_apoyo, pattern="^apoyo_")],
            LINK_VIDEO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_link)],
            FLYER: [
                MessageHandler(filters.PHOTO, finalizar_campana),
                CallbackQueryHandler(
                    finalizar_campana, pattern="^omitir_flyer$")
            ],
        },
        fallbacks=[CallbackQueryHandler(
            enviar_menu_principal, pattern="^volver_menu$")],
        per_message=False
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cupon", crear_cupon_comando))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(manejador_botones))
    application.add_handler(CallbackQueryHandler(
        procesar_cambios_vip, pattern="^setvip_"))
    application.add_handler(CallbackQueryHandler(
        procesar_aprobacion, pattern="^aprobar_|^rechazar_"))
    application.add_handler(CallbackQueryHandler(
        ver_tareas_disponibles, pattern="^ver_tareas$"))
    application.add_handler(CallbackQueryHandler(
        panel_administracion, pattern="^panel_admin$"))
    application.add_handler(CallbackQueryHandler(
        exportar_base_datos, pattern="^admin_backup$"))
    application.add_handler(MessageHandler(
        filters.PHOTO & ~filters.COMMAND, recibir_evidencia))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, manejador_mensajes))
    application.add_error_handler(error_handler)

    # 4. Inicializar DB de Render
    loop = asyncio.get_event_loop()
    loop.run_until_complete(inicializar_base_de_datos())

    # 5. Configurar Servidor Web aiohttp para Webhook
    app_web = web.Application()
    app_web['bot_app'] = application
    app_web.router.add_get('/', handle_health_check)
    app_web.router.add_post(f'/{TOKEN}', handle_webhook)

    app_web.on_startup.append(on_startup)
    app_web.on_cleanup.append(on_cleanup)

    # 6. Lanzar Servidor
    print(f"🚀 Iniciando servidor Webhook en puerto {PORT}...")
    web.run_app(app_web, host='0.0.0.0', port=PORT)


if __name__ == "__main__":
    main()
