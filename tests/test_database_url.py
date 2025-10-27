import os
from pathlib import Path
import sys

os.environ.setdefault("SKIP_DB_SETUP", "1")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test")
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_ANON_KEY", "anon")

APP_PATH = Path(__file__).resolve().parents[1] / "app"

if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from sqlalchemy.engine.url import make_url

from app.db import database


def test_normalize_asyncpg_url_enforces_cache_settings():
    normalized = database._normalize_database_url(
        "postgresql://user:pass@host/database"
    )

    url = make_url(normalized)

    assert url.drivername == "postgresql+asyncpg"
    assert url.query["statement_cache_size"] == "0"
    assert url.query["prepared_statement_cache_size"] == "0"


def test_normalize_asyncpg_url_overrides_existing_cache_settings():
    normalized = database._normalize_database_url(
        "postgresql://user:pass@host/database?statement_cache_size=25"
    )

    url = make_url(normalized)

    assert url.drivername == "postgresql+asyncpg"
    assert url.query["statement_cache_size"] == "0"
    assert url.query["prepared_statement_cache_size"] == "0"
