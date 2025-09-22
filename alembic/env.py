import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel
from dotenv import load_dotenv

# Ensure project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import all models so Alembic can detect metadata
from app.models import *

# Load environment variables
load_dotenv()

# Alembic Config
config = context.config

# Set sqlalchemy.url from .env (sync driver)
DB_URL = os.getenv("DB_URL")
if DB_URL and "asyncpg" in DB_URL:
    DB_URL = DB_URL.replace("+asyncpg", "+psycopg")  # Use sync psycopg for Alembic
    print(f"Alembic DB_URL (sync): {DB_URL}")
config.set_main_option("sqlalchemy.url", DB_URL)

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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()