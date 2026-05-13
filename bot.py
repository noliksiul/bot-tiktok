# =========================
# MÓDULO 1a - CONFIGURACIÓN GLOBAL
# =========================

import os
import json
import logging
from datetime import datetime
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, ConversationHandler
)
import psycopg2
import psycopg2.extras

# Variables de entorno (Render)
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Backup / Rescate
CONTEO_RESCATE_DATA = """
[AQUÍ SE PEGA EL JSON RECUPERADO SI MIGRAS]
"""

# Flask para servidor HTTP embebido
app = Flask(__name__)

# =========================
# MÓDULO 1b - CONEXIÓN A POSTGRESQL
# =========================


def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    return conn


def init_tables():
    conn = get_db()
    cur = conn.cursor()
    # Tabla users
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id BIGINT PRIMARY KEY,
        tiktok_user TEXT UNIQUE,
        balance INTEGER DEFAULT 10,
        es_vip BOOLEAN DEFAULT FALSE,
        rol TEXT,
        contador_ingresos INTEGER DEFAULT 1,
        referido_por BIGINT,
        contacto_vip TEXT,
        porcentaje_regalo_vip INTEGER DEFAULT 0
    );
    """)
    # Tabla movimientos
    cur.execute("""
    CREATE TABLE IF NOT EXISTS movimientos (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT,
        detalle TEXT,
        puntos INTEGER,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    # Tabla seguimientos
    cur.execute("""
    CREATE TABLE IF NOT EXISTS seguimientos (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT,
        link TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    # Tabla videos
    cur.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT,
        tipo TEXT,
        titulo TEXT,
        descripcion TEXT,
        link TEXT,
        es_propio BOOLEAN,
        meta_apoyo TEXT,
        file_id_flyer TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    # Tabla interacciones
    cur.execute("""
    CREATE TABLE IF NOT EXISTS interacciones (
        id SERIAL PRIMARY KEY,
        tipo TEXT,
        item_id INTEGER,
        actor_id BIGINT,
        owner_id BIGINT,
        status TEXT,
        puntos INTEGER,
        file_id_evidencia TEXT,
        token_web_terceros TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    conn.commit()
    cur.close()
    conn.close()

# =========================
# MÓDULO 2 - HANDLERS TELEGRAM
# =========================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Registro o actualización de contador
    cur.execute("SELECT * FROM users WHERE telegram_id=%s;", (user_id,))
    user = cur.fetchone()
    if user:
        cur.execute(
            "UPDATE users SET contador_ingresos=contador_ingresos+1 WHERE telegram_id=%s;", (user_id,))
    else:
        cur.execute(
            "INSERT INTO users (telegram_id, rol) VALUES (%s, %s);", (user_id, "usuario"))
    conn.commit()
    cur.close()
    conn.close()

    await update.message.reply_text("👋 Bienvenido al ecosistema Lord Nolik. Usa el menú para continuar.")


async def billetera(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT balance FROM users WHERE telegram_id=%s;", (user_id,))
    saldo = cur.fetchone()
    cur.execute(
        "SELECT * FROM movimientos WHERE telegram_id=%s ORDER BY created_at DESC LIMIT 5;", (user_id,))
    movimientos = cur.fetchall()
    cur.close()
    conn.close()

    texto = f"💰 Saldo actual: {saldo['balance'] if saldo else 0}\n\nÚltimos movimientos:\n"
    for m in movimientos:
        texto += f"{m['created_at'].strftime('%d-%m-%Y')} | {m['detalle']} | {m['puntos']} puntos\n"

    await update.message.reply_text(texto)

# =========================
# MÓDULO 3 - SERVIDOR HTTP EMBEBIDO
# =========================


@app.route("/")
def index():
    return "🌐 Lord Nolik Platform corriendo en Render."


@app.route("/admin")
def admin_dashboard():
    # Aquí podrías mostrar métricas globales
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT COUNT(*) AS total_users FROM users;")
    total_users = cur.fetchone()["total_users"]
    cur.execute("SELECT COUNT(*) AS total_vip FROM users WHERE es_vip=TRUE;")
    total_vip = cur.fetchone()["total_vip"]
    cur.close()
    conn.close()

    return f"👑 Panel del Administrador Supremo\nUsuarios totales: {total_users}\nVIP activos: {total_vip}"

# =========================
# MÓDULO 4a - PUBLICACIÓN DE VIDEOS (FLUJO INICIAL)
# =========================


# Estados de la conversación
TIPO_VIDEO, TITULO, DESCRIPCION, LINK, PROPIEDAD, META_APOYO, FLYER = range(7)


async def publicar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT balance FROM users WHERE telegram_id=%s;", (user_id,))
    saldo = cur.fetchone()
    cur.close()
    conn.close()

    if not saldo or saldo["balance"] < 5:
        await update.message.reply_text("⚠️ No tienes saldo suficiente (mínimo 5 monedas).")
        return ConversationHandler.END

    await update.message.reply_text("🎥 ¿Qué tipo de video deseas publicar?\nOpciones: normal, shop, live, evento_colaboracion")
    return TIPO_VIDEO


async def tipo_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tipo"] = update.message.text
    await update.message.reply_text("📌 Ingresa el título del video:")
    return TITULO


async def titulo_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["titulo"] = update.message.text
    await update.message.reply_text("📝 Ingresa la descripción del video:")
    return DESCRIPCION


async def descripcion_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["descripcion"] = update.message.text
    await update.message.reply_text("🔗 Ingresa el link del video:")
    return LINK

# =========================
# MÓDULO 4b - PUBLICACIÓN DE VIDEOS (PROPIEDAD, META Y FLYER)
# =========================


async def link_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["link"] = update.message.text
    # Preguntar propiedad
    keyboard = [
        [InlineKeyboardButton("Propio", callback_data="propio")],
        [InlineKeyboardButton("Tercero", callback_data="tercero")]
    ]
    await update.message.reply_text("📽️ ¿El video es propio o de un tercero?", reply_markup=InlineKeyboardMarkup(keyboard))
    return PROPIEDAD


async def propiedad_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["es_propio"] = True if query.data == "propio" else False

    # Preguntar meta de apoyo
    keyboard = [
        [InlineKeyboardButton("Solo Vistas", callback_data="solo_vistas")],
        [InlineKeyboardButton("Interacción Completa",
                              callback_data="completo")]
    ]
    await query.edit_message_text("🎯 Selecciona la meta de apoyo:", reply_markup=InlineKeyboardMarkup(keyboard))
    return META_APOYO


async def meta_apoyo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["meta_apoyo"] = query.data

    # Preguntar flyer opcional
    keyboard = [
        [InlineKeyboardButton("Adjuntar Flyer", callback_data="flyer")],
        [InlineKeyboardButton("Omitir", callback_data="omitir")]
    ]
    await query.edit_message_text("🖼️ ¿Deseas adjuntar un flyer promocional?", reply_markup=InlineKeyboardMarkup(keyboard))
    return FLYER


async def flyer_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "flyer":
        await query.edit_message_text("📷 Envía la imagen del flyer ahora.")
        return FLYER
    else:
        context.user_data["file_id_flyer"] = None
        await query.edit_message_text("✅ Datos completos, guardando campaña...")
        return ConversationHandler.END


async def flyer_guardar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Captura el file_id de la foto
    photo = update.message.photo[-1]
    context.user_data["file_id_flyer"] = photo.file_id
    await update.message.reply_text("✅ Flyer recibido, guardando campaña...")
    return ConversationHandler.END

# =========================
# MÓDULO 4c - GUARDAR CAMPAÑA EN POSTGRESQL
# =========================


async def guardar_campania(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    datos = context.user_data

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO videos (telegram_id, tipo, titulo, descripcion, link, es_propio, meta_apoyo, file_id_flyer)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s);
    """, (
        user_id,
        datos.get("tipo"),
        datos.get("titulo"),
        datos.get("descripcion"),
        datos.get("link"),
        datos.get("es_propio"),
        datos.get("meta_apoyo"),
        datos.get("file_id_flyer")
    ))
    conn.commit()
    cur.close()
    conn.close()

    await update.message.reply_text("🎬 Tu campaña ha sido publicada exitosamente.")
    context.user_data.clear()
    return ConversationHandler.END

# =========================
# INTEGRACIÓN DEL FLUJO DE CAMPAÑAS
# =========================

publicar_handler = ConversationHandler(
    entry_points=[CommandHandler("publicar", publicar_video)],
    states={
        TIPO_VIDEO: [MessageHandler(filters.TEXT & ~filters.COMMAND, tipo_video)],
        TITULO: [MessageHandler(filters.TEXT & ~filters.COMMAND, titulo_video)],
        DESCRIPCION: [MessageHandler(filters.TEXT & ~filters.COMMAND, descripcion_video)],
        LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, link_video)],
        PROPIEDAD: [CallbackQueryHandler(propiedad_video)],
        META_APOYO: [CallbackQueryHandler(meta_apoyo)],
        FLYER: [
            CallbackQueryHandler(flyer_video),
            MessageHandler(filters.PHOTO, flyer_guardar)
        ],
    },
    fallbacks=[CommandHandler("cancelar", lambda u,
                              c: ConversationHandler.END)]
)

# =========================
# MÓDULO 5 - DISTRIBUCIÓN Y ANTI-FRAUDE
# =========================


async def listar_tareas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Excluir campañas propias (anti-autoapoyo)
    cur.execute(
        "SELECT * FROM videos WHERE telegram_id!=%s ORDER BY created_at DESC;", (user_id,))
    videos = cur.fetchall()
    cur.close()
    conn.close()

    if not videos:
        await update.message.reply_text("📭 No hay campañas disponibles en este momento.")
        return

    texto = "📊 Campañas disponibles:\n\n"
    for v in videos:
        texto += f"🎥 {v['titulo']} ({v['tipo']})\n🔗 {v['link']}\n\n"

    await update.message.reply_text(texto)

# =========================
# SISTEMA DE ALERTAS ANTI-FRAUDE
# =========================


def verificar_alertas():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Detectar acumulación sospechosa de puntos
    cur.execute("""
        SELECT telegram_id, SUM(puntos) AS total_puntos, COUNT(*) AS num_movs
        FROM movimientos
        WHERE created_at > NOW() - INTERVAL '1 hour'
        GROUP BY telegram_id
        HAVING SUM(puntos) > 100;
    """)
    sospechosos = cur.fetchall()
    cur.close()
    conn.close()

    # Aquí podrías enviar alerta al Administrador Supremo
    for s in sospechosos:
        print(
            f"⚠️ ALERTA: Usuario {s['telegram_id']} acumuló {s['total_puntos']} puntos en 1 hora.")

# =========================
# MÓDULO 6 - SOPORTE TÉCNICO Y NÓMINA
# =========================

# --- Sensor de Evidencias ---


async def recibir_evidencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    file_id = photo.file_id

    conn = get_db()
    cur = conn.cursor()
    # Guardar interacción como pendiente
    cur.execute("""
        INSERT INTO interacciones (tipo, actor_id, owner_id, status, puntos, file_id_evidencia)
        VALUES (%s,%s,%s,%s,%s,%s);
    """, ("video", user_id, None, "pending", 0, file_id))
    conn.commit()
    cur.close()
    conn.close()

    await update.message.reply_text("📷 Evidencia recibida. Enviada al dueño de la campaña para arbitraje.")

# --- Arbitraje Privado ---


async def arbitraje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Este handler simula el envío al dueño con botones de aprobar/rechazar
    keyboard = [
        [InlineKeyboardButton("✅ Aprobar", callback_data="aprobar")],
        [InlineKeyboardButton("❌ Rechazar", callback_data="rechazar")]
    ]
    await update.message.reply_text("⚖️ Arbitraje de evidencia:", reply_markup=InlineKeyboardMarkup(keyboard))


async def decision_arbitraje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    decision = query.data

    if decision == "aprobar":
        await query.edit_message_text("✅ Evidencia aprobada. Se pagará al trabajador y al patrocinador.")
    else:
        await query.edit_message_text("❌ Evidencia rechazada. No se otorgarán puntos.")

# --- Panel de Subadmins ---


async def panel_subadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛠️ Panel de Subadmins:\n- Buscar usuarios\n- Auditar historial\n- Modificar estatus de interacciones")

# --- Nómina Automática ---


def nomina_staff():
    conn = get_db()
    cur = conn.cursor()
    # Depositar sueldo mensual
    cur.execute(
        "UPDATE users SET balance=balance+150 WHERE rol IN ('admin','subadmin');")
    conn.commit()
    cur.close()
    conn.close()
    print("💰 Nómina del staff aplicada automáticamente.")

# =========================
# MÓDULO 7 - MAIN Y ARRANQUE
# =========================


def main():
    logging.basicConfig(level=logging.INFO)
    init_tables()  # Inicializa las tablas en PostgreSQL

    application = Application.builder().token(TOKEN).build()

    # Handlers principales
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("billetera", billetera))
    application.add_handler(CommandHandler("tareas", listar_tareas))
    application.add_handler(CommandHandler("soporte", panel_subadmin))

    # Conversación de publicación de videos
    application.add_handler(publicar_handler)

    # Evidencias y arbitraje
    application.add_handler(MessageHandler(filters.PHOTO, recibir_evidencia))
    application.add_handler(CommandHandler("arbitraje", arbitraje))
    application.add_handler(CallbackQueryHandler(
        decision_arbitraje, pattern="^(aprobar|rechazar)$"))

    # Arranca Flask y Bot en paralelo
    from threading import Thread
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

    application.run_polling()


if __name__ == "__main__":
    main()
