import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel
from dotenv import load_dotenv

# Ensure project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import all models so Alembic can detect metadata
from app.models import *  # noqa: F403, F401

# Load environment variables
load_dotenv()

# Alembic Config
config = context.config

# Ensure Alembic reuses the application's database engine configuration.
from app.db.database import get_sync_database_url  # noqa: E402

sync_database_url = get_sync_database_url()
if sync_database_url:
    config.set_main_option("sqlalchemy.url", sync_database_url)

# Setup logging from alembic.ini
if config.config_file_name:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (sync)."""
    url = config.get_main_option("sqlalchemy.url")

    # ✅ Force Alembic to use psycopg2 for migrations
    # psycopg3 + reflection = DuplicatePreparedStatement errors
    if "+psycopg" in url:
        url = url.replace("+psycopg", "+psycopg2")

    connectable = create_engine(
        url,
        pool_pre_ping=True,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
