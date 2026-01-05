import logging
import os
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest
from dotenv import load_dotenv

# --- Configuración de logs ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG,
)

# --- Cargar variables de entorno ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# --- Conexión a Supabase/Postgres ---
def get_connection():
    return psycopg2.connect(DATABASE_URL)

# --- Config de puntos ---
PUNTOS_APOYO_SEGUIMIENTO = 2
PUNTOS_APOYO_VIDEO = 3

# --- Utilidades ---
def back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")]]
    )
# --- Inicio y registro ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO users (telegram_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
    conn.commit()
    cur.close()
    conn.close()

    await update.message.reply_text(
        f"👋 Hola {update.effective_user.first_name}, bienvenido al bot de apoyo TikTok.\n"
        "Por favor escribe tu usuario de TikTok para registrarte.",
        reply_markup=back_to_menu_keyboard(),
    )
    context.user_data["state"] = "tiktok_user"

async def save_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text.strip()
    user_id = update.effective_user.id
    if not tiktok_user:
        await update.message.reply_text("⚠️ Envía un usuario válido.", reply_markup=back_to_menu_keyboard())
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET tiktok_user=%s WHERE telegram_id=%s", (tiktok_user, user_id))
    conn.commit()
    cur.close()
    conn.close()

    await show_main_menu(update, context, f"✅ Usuario TikTok registrado: {tiktok_user}")
    context.user_data["state"] = None

# --- Menú principal ---
async def show_main_menu(update_or_query, context: ContextTypes.DEFAULT_TYPE, message="🏠 Menú principal:"):
    keyboard = [
        [InlineKeyboardButton("📈 Subir seguimiento", callback_data="subir_seguimiento")],
        [InlineKeyboardButton("🎥 Subir video", callback_data="subir_video")],
        [InlineKeyboardButton("👀 Ver seguimiento", callback_data="ver_seguimiento")],
        [InlineKeyboardButton("📺 Ver video", callback_data="ver_video")],
        [InlineKeyboardButton("💰 Balance e historial", callback_data="balance")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if isinstance(update_or_query, Update) and update_or_query.message:
        await update_or_query.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(message, reply_markup=reply_markup)
# --- Subir seguimiento ---
async def save_seguimiento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    user_id = update.effective_user.id

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT tiktok_user, balance FROM users WHERE telegram_id=%s", (user_id,))
    row = cur.fetchone()

    if not row:
        await update.message.reply_text("❌ No estás registrado. Usa /start primero.", reply_markup=back_to_menu_keyboard())
        context.user_data["state"] = None
        cur.close(); conn.close()
        return

    tiktok_user, balance = row
    if balance < 3:
        await update.message.reply_text("⚠️ No tienes suficientes puntos para subir seguimiento (mínimo 3).", reply_markup=back_to_menu_keyboard())
        context.user_data["state"] = None
        cur.close(); conn.close()
        return

    cur.execute("INSERT INTO seguimientos (telegram_id, link) VALUES (%s, %s)", (user_id, link))
    conn.commit()

    cur.execute("UPDATE users SET balance = balance - 3 WHERE telegram_id=%s", (user_id,))
    conn.commit()

    cur.execute(
        "INSERT INTO movimientos (telegram_id, detalle, puntos) VALUES (%s, %s, %s)",
        (user_id, "Subir seguimiento", -3),
    )
    conn.commit()

    cur.close(); conn.close()

    await update.message.reply_text("✅ Tu seguimiento se subió con éxito.", reply_markup=back_to_menu_keyboard())
    context.user_data["state"] = None

# --- Subir video: flujo guiado (título → descripción → link) ---
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

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT tiktok_user, balance FROM users WHERE telegram_id=%s", (user_id,))
    row = cur.fetchone()

    if not row:
        await update.message.reply_text("❌ No estás registrado. Usa /start primero.", reply_markup=back_to_menu_keyboard())
        context.user_data["state"] = None
        cur.close(); conn.close()
        return

    tiktok_user, balance = row
    if balance < 5:
        await update.message.reply_text("⚠️ No tienes suficientes puntos para subir video (mínimo 5).", reply_markup=back_to_menu_keyboard())
        context.user_data["state"] = None
        cur.close(); conn.close()
        return

    cur.execute(
        "INSERT INTO videos (telegram_id, tipo, titulo, descripcion, link) VALUES (%s, %s, %s, %s, %s)",
        (user_id, context.user_data.get("video_tipo"), context.user_data.get("video_title"),
         context.user_data.get("video_desc"), link),
    )
    conn.commit()

    cur.execute("UPDATE users SET balance = balance - 5 WHERE telegram_id=%s", (user_id,))
    conn.commit()

    cur.execute(
        "INSERT INTO movimientos (telegram_id, detalle, puntos) VALUES (%s, %s, %s)",
        (user_id, "Subir video", -5),
    )
    conn.commit()

    cur.close(); conn.close()

    await update.message.reply_text("✅ Tu video se subió con éxito.", reply_markup=back_to_menu_keyboard())
    context.user_data["state"] = None
# --- Ver seguimientos ---
async def show_seguimientos(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    user_id = update_or_query.effective_user.id if isinstance(update_or_query, Update) else update_or_query.from_user.id

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, telegram_id, link, created_at FROM seguimientos WHERE telegram_id != %s ORDER BY created_at DESC",
        (user_id,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()

    if not rows:
        texto = "⚠️ No hay seguimientos disponibles por ahora."
        reply_markup = back_to_menu_keyboard()
        if isinstance(update_or_query, Update):
            await update_or_query.message.reply_text(texto, reply_markup=reply_markup)
        else:
            await update_or_query.edit_message_text(texto, reply_markup=reply_markup)
        return

    seg_id, owner_id, link, created_at = rows[0]
    keyboard = [
        [InlineKeyboardButton("🟡 Ya lo seguí ✅", callback_data=f"seguimiento_done_{seg_id}")],
        [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")],
    ]
    texto = f"👀 Seguimiento:\n🔗 {link}\n🗓️ {created_at}\n\nPulsa el botón si ya seguiste."
    markup = InlineKeyboardMarkup(keyboard)

    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(texto, reply_markup=markup)
    else:
        await update_or_query.edit_message_text(texto, reply_markup=markup)

# --- Ver videos ---
async def show_videos(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    user_id = update_or_query.effective_user.id if isinstance(update_or_query, Update) else update_or_query.from_user.id

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, telegram_id, tipo, titulo, descripcion, link, created_at FROM videos WHERE telegram_id != %s ORDER BY created_at DESC",
        (user_id,),
    )
    rows = cur.fetchall()
    cur.close(); conn.close()

    if not rows:
        texto = "⚠️ No hay videos disponibles por ahora."
        reply_markup = back_to_menu_keyboard()
        if isinstance(update_or_query, Update):
            await update_or_query.message.reply_text(texto, reply_markup=reply_markup)
        else:
            await update_or_query.edit_message_text(texto, reply_markup=reply_markup)
        return

    vid_id, owner_id, tipo, titulo, descripcion, link, created_at = rows[0]
    keyboard = [
        [InlineKeyboardButton("🟡 Ya apoyé (like/compartir) ⭐", callback_data=f"video_support_done_{vid_id}")],
        [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")],
    ]
    texto = (
        f"📺 Video ({tipo}):\n"
        f"📌 {titulo}\n"
        f"📝 {descripcion}\n"
        f"🔗 {link}\n"
        f"🗓️ {created_at}\n\nPulsa el botón si ya apoyaste."
    )
    markup = InlineKeyboardMarkup(keyboard)

    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(texto, reply_markup=markup)
    else:
        await update_or_query.edit_message_text(texto, reply_markup=markup)

# --- Solicitud de apoyo seguimiento ---
async def handle_seguimiento_done(query, context: ContextTypes.DEFAULT_TYPE, seg_id: int):
    actor_id = query.from_user.id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM seguimientos WHERE id=%s", (seg_id,))
    row = cur.fetchone()

    if not row:
        await query.edit_message_text("❌ Seguimiento no disponible.", reply_markup=back_to_menu_keyboard())
        cur.close(); conn.close()
        return
    owner_id = row[0]

    cur.execute(
        "SELECT id, status FROM interacciones WHERE tipo='seguimiento' AND item_id=%s AND actor_id=%s",
        (seg_id, actor_id),
    )
    exists = cur.fetchone()
    if exists:
        _, status = exists
        await query.edit_message_text(f"⚠️ Ya registraste apoyo para este seguimiento (estado: {status}).", reply_markup=back_to_menu_keyboard())
        cur.close(); conn.close()
        return

    cur.execute(
        "INSERT INTO interacciones (tipo, item_id, actor_id, owner_id, status, puntos) VALUES ('seguimiento', %s, %s, %s, 'pending', %s)",
        (seg_id, actor_id, owner_id, PUNTOS_APOYO_SEGUIMIENTO),
    )
    conn.commit()
    cur.execute("SELECT currval(pg_get_serial_sequence('interacciones','id'))")
    inter_id = cur.fetchone()[0]

    await query.edit_message_text("🟡 Listo, se notificó al dueño para aprobación.", reply_markup=back_to_menu_keyboard())

    cur.execute("SELECT tiktok_user FROM users WHERE telegram_id=%s", (actor_id,))
    actor_tt_row = cur.fetchone()
    actor_tt = actor_tt_row[0] if actor_tt_row and actor_tt_row[0] else f"{actor_id}"

    keyboard = [
        [InlineKeyboardButton("✅ Aceptar", callback_data=f"approve_interaction_{inter_id}")],
        [InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_interaction_{inter_id}")],
        [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")],
    ]
    try:
        await context.bot.send_message(
            chat_id=owner_id,
            text=f"📈 Solicitud: @{actor_tt} indica que ya siguió tu perfil.\nID: {inter_id}\n¿Aceptas otorgar {PUNTOS_APOYO_SEGUIMIENTO} puntos?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logging.warning(f"No se pudo notificar al dueño del seguimiento: {e}")

    cur.close(); conn.close()

# --- Solicitud de apoyo video ---
async def handle_video_support_done(query, context: ContextTypes.DEFAULT_TYPE, vid_id: int):
    actor_id = query.from_user.id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM videos WHERE id=%s", (vid_id,))
    row = cur.fetchone()

    if not row:
        await query.edit_message_text("❌ Video no disponible.", reply_markup=back_to_menu_keyboard())
        cur.close(); conn.close()
        return
    owner_id = row[0]

    cur.execute(
        "SELECT id, status FROM interacciones WHERE tipo='video_support' AND item_id=%s AND actor_id=%s",
        (vid_id, actor_id),
    )
    exists = cur.fetchone()
    if exists:
        _, status = exists
        await query.edit_message_text(f"⚠️ Ya registraste apoyo para este video (estado: {status}).", reply_markup=back_to_menu_keyboard())
        cur.close(); conn.close()
        return

    cur.execute(
        "INSERT INTO interacciones (tipo, item_id, actor_id, owner_id, status, puntos) VALUES ('video_support', %s, %s, %s, 'pending', %s)",
        (vid_id, actor_id, owner_id, PUNTOS_APOYO_VIDEO),
    )
    conn.commit()
    cur.execute("SELECT currval(pg_get_serial_sequence('interacciones','id'))")
    inter_id = cur.fetchone()[0]

    await query.edit_message_text("🟡 Listo, se notificó al dueño para aprobación.", reply_markup=back_to_menu_keyboard())

    cur.execute("SELECT tiktok_user FROM users WHERE telegram_id=%s", (actor_id,))
    actor_tt_row = cur.fetchone()
    actor_tt = actor_tt_row[0] if actor_tt_row and actor_tt_row[0] else f"{actor_id}"

    keyboard = [
        [InlineKeyboardButton("✅ Aceptar", callback_data=f"approve_interaction_{inter_id}")],
        [InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_interaction_{inter_id}")],
        [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")],
    ]
    try:
        await context.bot.send_message(
            chat_id=owner_id,
            text=f"🎥 Solicitud: @{actor_tt} indica que ya apoyó tu video (like/compartir).\nID: {inter_id}\n¿Aceptas otorgar {PUNTOS_APOYO_VIDEO} puntos?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logging.warning(f"No se pudo notificar al dueño del video: {e}")

    cur.close(); conn.close()
# --- Aprobar interacción ---
async def approve_interaction(query, context: ContextTypes.DEFAULT_TYPE, inter_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT tipo, actor_id, owner_id, status, puntos FROM interacciones WHERE id=%s", (inter_id,))
    row = cur.fetchone()

    if not row:
        await query.edit_message_text("❌ Interacción no encontrada.", reply_markup=back_to_menu_keyboard())
        cur.close(); conn.close()
        return
    tipo, actor_id, owner_id, status, puntos = row

    if query.from_user.id != owner_id:
        await query.answer("No puedes aprobar esta interacción.", show_alert=True)
        cur.close(); conn.close()
        return
    if status != "pending":
        await query.edit_message_text(f"⚠️ Esta interacción ya está en estado: {status}.", reply_markup=back_to_menu_keyboard())
        cur.close(); conn.close()
        return

    cur.execute("UPDATE interacciones SET status='accepted' WHERE id=%s", (inter_id,))
    conn.commit()
    cur.execute("UPDATE users SET balance = balance + %s WHERE telegram_id=%s", (puntos, actor_id))
    conn.commit()
    cur.execute(
        "INSERT INTO movimientos (telegram_id, detalle, puntos) VALUES (%s, %s, %s)",
        (actor_id, f"Apoyo {tipo} aprobado", puntos),
    )
    conn.commit()

    cur.close(); conn.close()

    await query.edit_message_text("✅ Interacción aprobada. Puntos otorgados.", reply_markup=back_to_menu_keyboard())
    try:
        await context.bot.send_message(
            chat_id=actor_id,
            text=f"✅ Tu apoyo en {tipo} fue aprobado. Ganaste {puntos} puntos.",
        )
    except Exception as e:
        logging.warning(f"No se pudo notificar al actor: {e}")

# --- Rechazar interacción ---
async def reject_interaction(query, context: ContextTypes.DEFAULT_TYPE, inter_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT tipo, actor_id, owner_id, status FROM interacciones WHERE id=%s", (inter_id,))
    row = cur.fetchone()

    if not row:
        await query.edit_message_text("❌ Interacción no encontrada.", reply_markup=back_to_menu_keyboard())
        cur.close(); conn.close()
        return
    tipo, actor_id, owner_id, status = row

    if query.from_user.id != owner_id:
        await query.answer("No puedes rechazar esta interacción.", show_alert=True)
        cur.close(); conn.close()
        return
    if status != "pending":
        await query.edit_message_text(f"⚠️ Esta interacción ya está en estado: {status}.", reply_markup=back_to_menu_keyboard())
        cur.close(); conn.close()
        return

    cur.execute("UPDATE interacciones SET status='rejected' WHERE id=%s", (inter_id,))
    conn.commit()

    cur.close(); conn.close()

    await query.edit_message_text("❌ Interacción rechazada.", reply_markup=back_to_menu_keyboard())
    try:
        await context.bot.send_message(
            chat_id=actor_id,
            text=f"❌ Tu apoyo en {tipo} fue rechazado.",
        )
    except Exception as e:
        logging.warning(f"No se pudo notificar al actor: {e}")

# --- Balance e historial ---
async def show_balance(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    is_update = isinstance(update_or_query, Update)
    user_id = update_or_query.effective_user.id if is_update else update_or_query.from_user.id

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO users (telegram_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
    conn.commit()

    cur.execute("SELECT balance FROM users WHERE telegram_id=%s", (user_id,))
    row = cur.fetchone()
    balance = row[0] if row else 0

    cur.execute(
        """
        SELECT detalle, puntos, created_at
        FROM movimientos
        WHERE telegram_id=%s
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (user_id,),
    )
    movimientos = cur.fetchall()

    cur.close(); conn.close()

    texto = f"💰 Tu balance actual: {balance} puntos\n\n📜 Últimos movimientos:\n"
    if movimientos:
        for detalle, puntos, fecha in movimientos:
            texto += f"- {detalle}: {puntos} puntos ({fecha})\n"
    else:
        texto += "⚠️ No tienes historial todavía."

    reply_markup = back_to_menu_keyboard()

    if is_update and getattr(update_or_query, "message", None):
        await update_or_query.message.reply_text(texto, reply_markup=reply_markup)
    else:
        await update_or_query.edit_message_text(texto, reply_markup=reply_markup)

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_balance(update, context)

# --- Handler de texto ---
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
            reply_markup=back_to_menu_keyboard(),
        )

# --- Menú y callbacks principales ---
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    data = query.data

    if data == "subir_seguimiento":
        await query.edit_message_text(
            "🔗 Envía tu link de perfil de TikTok para publicar tu seguimiento (costo: 3 puntos).",
            reply_markup=back_to_menu_keyboard(),
        )
        context.user_data["state"] = "seguimiento_link"

    elif data == "subir_video":
        keyboard = [
            [InlineKeyboardButton("🎬 Normal", callback_data="video_tipo_normal")],
            [InlineKeyboardButton("🎤 Incentivo Live", callback_data="video_tipo_live")],
            [InlineKeyboardButton("🎉 Evento", callback_data="video_tipo_evento")],
            [InlineKeyboardButton("🛍️ TikTok Shop", callback_data="video_tipo_shop")],
            [InlineKeyboardButton("🤝 Colaboración", callback_data="video_tipo_colaboracion")],
            [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")],
        ]
        await query.edit_message_text("📌 ¿Qué tipo de video quieres subir?", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["state"] = None

    elif data.startswith("video_tipo_"):
        tipos = {
            "video_tipo_normal": "Normal",
            "video_tipo_live": "Incentivo Live",
            "video_tipo_evento": "Evento",
            "video_tipo_shop": "TikTok Shop",
            "video_tipo_colaboracion": "Colaboración",
        }
        context.user_data["video_tipo"] = tipos.get(data, "Normal")
        context.user_data["state"] = "video_title"
        await query.edit_message_text(
            f"🎬 Tipo seleccionado: {context.user_data['video_tipo']}\n\nAhora envíame el título de tu video:",
            reply_markup=back_to_menu_keyboard(),
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
        # --- Menú y callbacks principales ---
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    data = query.data

    if data == "subir_seguimiento":
        await query.edit_message_text(
            "🔗 Envía tu link de perfil de TikTok para publicar tu seguimiento (costo: 3 puntos).",
            reply_markup=back_to_menu_keyboard(),
        )
        context.user_data["state"] = "seguimiento_link"

    elif data == "subir_video":
        keyboard = [
            [InlineKeyboardButton("🎬 Normal", callback_data="video_tipo_normal")],
            [InlineKeyboardButton("🎤 Incentivo Live", callback_data="video_tipo_live")],
            [InlineKeyboardButton("🎉 Evento", callback_data="video_tipo_evento")],
            [InlineKeyboardButton("🛍️ TikTok Shop", callback_data="video_tipo_shop")],
            [InlineKeyboardButton("🤝 Colaboración", callback_data="video_tipo_colaboracion")],
            [InlineKeyboardButton("🔙 Regresar al menú principal", callback_data="menu_principal")],
        ]
        await query.edit_message_text("📌 ¿Qué tipo de video quieres subir?", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["state"] = None

    elif data.startswith("video_tipo_"):
        tipos = {
            "video_tipo_normal": "Normal",
            "video_tipo_live": "Incentivo Live",
            "video_tipo_evento": "Evento",
            "video_tipo_shop": "TikTok Shop",
            "video_tipo_colaboracion": "Colaboración",
        }
        context.user_data["video_tipo"] = tipos.get(data, "Normal")
        context.user_data["state"] = "video_title"
        await query.edit_message_text(
            f"🎬 Tipo seleccionado: {context.user_data['video_tipo']}\n\nAhora envíame el título de tu video:",
            reply_markup=back_to_menu_keyboard(),
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
def main():
    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=10.0,
    )

    app = Application.builder().token(BOT_TOKEN).request(request).build()

    # Handlers principales
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CallbackQueryHandler(menu_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🤖 Bot iniciado y escuchando...")
    app.run_polling(poll_interval=1.0, timeout=30, bootstrap_retries=5, close_loop=False)

if __name__ == "__main__":
    main()
