import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from sqlalchemy import Column, BigInteger, Integer, Text, TIMESTAMP, ForeignKey, func, CheckConstraint
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

class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(Text)
    first_name = Column(Text)
    last_name = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())

class Balance(Base):
    __tablename__ = "balances"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    balance = Column(Integer, default=0)
    updated_at = Column(TIMESTAMP, server_default=func.now())

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Integer, nullable=False)
    type = Column(Text, nullable=False)  # 'credit' | 'debit'
    description = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
    __table_args__ = (CheckConstraint("type IN ('credit','debit')", name="type_check"),)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Bienvenido! Tu cuenta está lista.")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Tu balance actual es: 0")

async def credit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Función de crédito aún no implementada.")

async def debit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Función de débito aún no implementada.")

def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("credit", credit_cmd))
    app.add_handler(CommandHandler("debit", debit_cmd))
    return app

# --- Bloque final corregido ---
if __name__ == "__main__":
    asyncio.run(init_db())          # Inicializa DB
    app = build_app()
    app.run_polling(close_loop=False)  # Arranca bot sin cerrar el loop