import os
import logging
import asyncpg
import asyncio
from flask import Flask, request, send_from_directory
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, ContextTypes, CallbackQueryHandler, MessageHandler, CommandHandler, filters

# 🔑 Configuración
TOKEN = os.getenv("TOKEN")  # Render debe tener la variable TOKEN
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN:
    raise ValueError("❌ No se encontró la variable TOKEN en Render")

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

# Crear tablas


async def init_db():
    # Conexión con sslmode=require (si lo pusiste en la variable de entorno)
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        tiktok_user TEXT,
        puntos NUMERIC DEFAULT 0
    );""")
    await conn.execute("""CREATE TABLE IF NOT EXISTS movimientos (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(id),
        descripcion TEXT,
        puntos NUMERIC,
        fecha TIMESTAMP DEFAULT NOW()
    );""")
    await conn.close()

# Handlers


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📋 Registrar TikTok", callback_data="registro")],
        [InlineKeyboardButton("🎥 Video de ejemplo",
          web_app=WebAppInfo(f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/index.html"))],
        [InlineKeyboardButton("💳 Saldo", callback_data="saldo")],
        [InlineKeyboardButton("📜 Últimos 5 Movimientos",
                              callback_data="movimientos")]
    ]
    if update.message:
        await update.message.reply_text("Menú principal:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.message.reply_text("Menú principal:", reply_markup=InlineKeyboardMarkup(keyboard))


async def registrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("✍️ Escribe tu usuario de TikTok:")


async def guardar_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tiktok_user = update.message.text
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        INSERT INTO users (telegram_id, tiktok_user, puntos)
        VALUES ($1, $2, 0)
        ON CONFLICT (telegram_id) DO UPDATE SET tiktok_user=$2
    """, update.effective_user.id, tiktok_user)
    await conn.close()
    await update.message.reply_text(f"✅ Usuario TikTok registrado: {tiktok_user}")

# Recibir datos de la miniapp


async def recibir_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.web_app_data and update.message.web_app_data.data == "continuar":
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("UPDATE users SET puntos = puntos + 2 WHERE telegram_id=$1", update.effective_user.id)
        await conn.execute("""
            INSERT INTO movimientos (user_id, descripcion, puntos)
