# app/database.py
from __future__ import annotations

import os
from typing import Any, AsyncGenerator, Dict, Optional

from dotenv import load_dotenv
from sqlalchemy.engine import URL
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Load environment variables from a .env file if present so that running the
# application locally works without manually exporting variables.
load_dotenv()


def _normalize_database_url(raw_url: Optional[str]) -> Optional[str]:
    """Return a SQLAlchemy URL string tailored for async ``asyncpg`` usage.

    The Supabase pooled connection lives on port ``6543`` (via PgBouncer in
    transaction mode). When the provided URL targets a Supabase host we ensure
    that port is used so the application benefits from the connection pool.
    Additionally, any PostgreSQL URLs are coerced to the ``+asyncpg`` driver so
    the async engine works correctly.
    """

    if not raw_url:
        return raw_url

    url: URL = make_url(raw_url)
    drivername = url.drivername

    if drivername.startswith("postgresql") and "+asyncpg" not in drivername:
        url = url.set(drivername="postgresql+asyncpg")
        drivername = url.drivername

    if (url.host or "").find("supabase") != -1 and url.port != 6543:
        url = url.set(port=6543)

    if "asyncpg" in drivername:
        url = url.update_query_dict(
            {
                "statement_cache_size": "0",
                "prepared_statement_cache_size": "0",
            }
        )

    return url.render_as_string(hide_password=False)


def _default_connect_args(url: Optional[str]) -> Dict[str, Any]:
    """Provide driver-appropriate ``connect_args`` for SQLAlchemy engines."""

    if not url:
        return {}

    drivername = make_url(url).drivername
    if "asyncpg" in drivername:
        return {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        }

    return {}


def create_engine_from_url(
    database_url: Optional[str],
    *,
    connect_args: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> AsyncEngine:
    """Create an ``AsyncEngine`` with PgBouncer-safe defaults.

    The returned engine always disables asyncpg's prepared statement caches to
    avoid ``duplicate prepared statement" errors when PgBouncer operates in
    transaction pooling mode (the configuration used by Supabase).
    """

    normalized_url = _normalize_database_url(database_url)
    default_connect_args = _default_connect_args(normalized_url)
    merged_connect_args = {**default_connect_args, **(connect_args or {})}

    return create_async_engine(
        normalized_url,
        connect_args=merged_connect_args,
        **kwargs,
    )


DATABASE_URL = _normalize_database_url(os.getenv("DB_URL"))  # Add to your .env

engine: AsyncEngine = create_engine_from_url(
    DATABASE_URL,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


def get_sync_database_url() -> Optional[str]:
    """Return a sync-compatible URL (``+psycopg``) for Alembic migrations."""

    if not DATABASE_URL:
        return DATABASE_URL

    url = make_url(DATABASE_URL)
    if url.drivername.endswith("+asyncpg"):
        url = url.set(drivername=url.drivername.replace("+asyncpg", "+psycopg"))
    return url.render_as_string(hide_password=False)
