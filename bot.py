import os
import asyncio
import threading
from flask import Flask
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
    async with async_session() as session:
        user = await session.get(User, update.effective_user.id)
        if not user:
            user = User(
                id=update.effective_user.id,
                telegram_id=update.effective_user.id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name,
            )
            session.add(user)
            session.add(Balance(user_id=user.id, balance=0))
            await session.commit()
        await update.message.reply_text("¡Bienvenido! Tu cuenta está lista.")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with async_session() as session:
        user = await session.get(User, update.effective_user.id)
        if not user:
            await update.message.reply_text("Primero usa /start para crear tu cuenta.")
            return
        balance = await session.get(Balance, user.id)
        await update.message.reply_text(f"Tu balance actual es: {balance.balance}")

async def credit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1 or not context.args[0].isdigit():
        await update.message.reply_text("Uso: /credit <monto>")
        return
    amount = int(context.args[0])
    async with async_session() as session:
        user = await session.get(User, update.effective_user.id)
        if not user:
            await update.message.reply_text("Primero usa /start para crear tu cuenta.")
            return
        balance = await session.get(Balance, user.id)
        balance.balance += amount
        session.add(Transaction(user_id=user.id, amount=amount, type="credit", description="Ingreso"))
        await session.commit()
        await update.message.reply_text(f"Se acreditaron {amount}. Nuevo balance: {balance.balance}")

async def debit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1 or not context.args[0].isdigit():
        await update.message.reply_text("Uso: /debit <monto>")
        return
    amount = int(context.args[0])
    async with async_session() as session:
        user = await session.get(User, update.effective_user.id)
        if not user:
            await update.message.reply_text("Primero usa /start para crear tu cuenta.")
            return
        balance = await session.get(Balance, user.id)
        if balance.balance < amount:
            await update.message.reply_text("Fondos insuficientes.")
            return
        balance.balance -= amount
        session.add(Transaction(user_id=user.id, amount=amount, type="debit", description="Retiro"))
        await session.commit()
        await update.message.reply_text(f"Se debitó {amount}. Nuevo balance: {balance.balance}")

def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("credit", credit_cmd))
    app.add_handler(CommandHandler("debit", debit_cmd))
    return app

# --- Mini servidor Flask para Render ---
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot de Telegram corriendo en Render!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

# --- Bloque final ---
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    app = build_app()
    app.run_polling(close_loop=False)