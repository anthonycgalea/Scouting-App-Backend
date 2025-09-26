# app/database.py
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
import os
from dotenv import load_dotenv

# Load environment variables from a .env file if present so that running the
# application locally works without manually exporting variables.
load_dotenv()

DATABASE_URL = os.getenv("DB_URL")  # Add to your .env

# Ensure the URL uses SQLAlchemy's async driver. If the environment provides a
# sync driver or no driver at all, convert it to use ``+asyncpg`` so that the
# async engine works correctly.
if DATABASE_URL and "+asyncpg" not in DATABASE_URL:
    if "+psycopg" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("+psycopg", "+asyncpg")
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine: AsyncEngine = create_async_engine(DATABASE_URL)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session():
    async with AsyncSession(engine) as session:
        yield session