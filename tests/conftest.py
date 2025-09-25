import asyncio
import os

import pytest
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DB_URL", "sqlite+aiosqlite://")

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

async_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
AsyncSessionLocal = sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_session():
    async with AsyncSessionLocal() as session:
        yield session


async def _create_tables():
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def _drop_tables():
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    from app.main import app
    from app.db.database import get_session

    app.dependency_overrides[get_session] = override_get_session
    asyncio.run(_create_tables())
    yield
    asyncio.run(_drop_tables())
    app.dependency_overrides.pop(get_session, None)
