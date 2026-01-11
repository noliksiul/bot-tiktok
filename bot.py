import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from sqlalchemy import Column, BigInteger, Integer, Text, TIMESTAMP, ForeignKey, func, CheckConstraint, select
from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# --- Configuración de la base de datos ---
DATABASE_URL = os.getenv("DATABASE_URL")

# Forzar a usar psycopg v3
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://")
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()

# --- Modelos ---
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
    type = Column(Text, nullable=False)
    description = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
    __table_args__ = (CheckConstraint("type IN ('credit','debit')", name="type_check"),)

# --- Funciones de servicio ---
async def upsert_user(session, telegram_id, username=None, first_name=None, last_name=None):
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(telegram_id=telegram_id, username=username, first_name=first_name, last_name=last_name)
        session.add(user)
        await session.flush()
        balance = Balance(user_id=user.id, balance=0)
        session.add(balance)
        await session.flush()
    return user

async def get_balance(session, telegram_id):
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        return 0
    result = await session.execute(select(Balance).where(Balance.user_id == user.id))
    balance = result.scalar_one_or_none()
    return balance.balance if balance else 0

async def apply_transaction(session, telegram_id, amount, tx_type, description=None):
    user = await upsert_user(session, telegram_id)
    delta = amount if tx_type == "credit" else -amount
    tx = Transaction(user_id=user.id, amount=amount, type=tx_type, description=description)
    session.add(tx)
    result = await session.execute(select(Balance).where(Balance.user_id == user.id).with_for_update())
    balance = result.scalar_one()
    balance.balance += delta
    await session.flush()
    return balance.balance

# --- Bot de Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    async with async_session() as session:
        async with session.begin():
            await upsert_user(session, user.id, user.username, user.first_name, user.last_name)
    await update.message.reply_text("¡Bienvenido! Tu cuenta está lista.")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    async with async_session() as session:
        bal = await get_balance(session, user.id)
    await update.message.reply_text(f"Tu balance actual es: {bal}")

async def credit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    if not args:
        await update.message.reply_text("Uso: /credit Monto")
        return
    amount = int(args[0])
    async with async_session() as session:
        async with session.begin():
            new_bal = await apply_transaction(session, user.id, amount, "credit", "Crédito manual")
    await update.message.reply_text(f"Crédito aplicado. Nuevo balance: {new_bal}")

async def debit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    if not args:
        await update.message.reply_text("Uso: /debit Monto")
        return
    amount = int(args[0])
    async with async_session() as session:
        async with session.begin():
            new_bal = await apply_transaction(session, user.id, amount, "debit", "Débito manual")
    await update.message.reply_text(f"Débito aplicado. Nuevo balance: {new_bal}")

def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("credit", credit_cmd))
    app.add_handler(CommandHandler("debit", debit_cmd))
    return app

if __name__ == "__main__":
    asyncio.run(init_db())
    app = build_app()
    asyncio.run(app.run_polling())