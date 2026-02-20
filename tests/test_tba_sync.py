import asyncio
import os

from sqlmodel import select

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

from app.models import FRCEvent
from app.services import tba_sync
from tests.conftest import AsyncSessionLocal


class _MockResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _MockAsyncClient:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, headers):
        return _MockResponse(self._payload)


async def _run_import_events_with_preseason() -> list[FRCEvent]:
    payload = [
        {
            "key": "2099week0a",
            "name": "Preseason Scrimmage",
            "short_name": "Week 0 A",
            "event_type": 100,
            "week": None,
        },
        {
            "key": "2099miket",
            "name": "Kettering",
            "short_name": "Kettering",
            "event_type": 1,
            "week": 0,
        },
    ]

    original_client = tba_sync.httpx.AsyncClient
    original_api_key = tba_sync.TBA_API_KEY
    tba_sync.TBA_API_KEY = "test-key"
    tba_sync.httpx.AsyncClient = lambda *args, **kwargs: _MockAsyncClient(payload)

    try:
        async with AsyncSessionLocal() as session:
            await tba_sync.import_event_registration(2099, session)

            result = await session.exec(
                select(FRCEvent).where(FRCEvent.year == 2099).order_by(FRCEvent.event_key)
            )
            return result.all()
    finally:
        tba_sync.httpx.AsyncClient = original_client
        tba_sync.TBA_API_KEY = original_api_key


def test_import_event_registration_includes_preseason_event_type_100(setup_database):
    events = asyncio.run(_run_import_events_with_preseason())

    keys = [event.event_key for event in events]
    assert "2099week0a" in keys
    assert "2099miket" in keys

    preseason = next(event for event in events if event.event_key == "2099week0a")
    assert preseason.week == 0
