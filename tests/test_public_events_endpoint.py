import asyncio
import os
from typing import Any

from fastapi.testclient import TestClient

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

from app.main import app
from app.models import FRCEvent
from app.services import event as event_service
from tests.conftest import AsyncSessionLocal


async def _prepare_events() -> list[FRCEvent]:
    async with AsyncSessionLocal() as session:
        events = [
            FRCEvent(
                event_key="2024test1",
                event_name="Test Event 1",
                short_name="Test1",
                year=2024,
                week=1,
            ),
            FRCEvent(
                event_key="2024test2",
                event_name="Test Event 2",
                short_name=None,
                year=2024,
                week=2,
            ),
        ]
        session.add_all(events)
        await session.commit()
        for event in events:
            await session.refresh(event)
        return events


def test_list_events_uses_event_name_when_short_name_missing(setup_database):
    created_events = asyncio.run(_prepare_events())

    with TestClient(app) as client:
        response = client.get("/public/events/2024")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == len(created_events)

    event_with_short_name = next(
        event for event in data if event["event_key"] == "2024test1"
    )
    assert event_with_short_name["short_name"] == "Test1"

    event_without_short_name = next(
        event for event in data if event["event_key"] == "2024test2"
    )
    assert event_without_short_name["short_name"] == "Test Event 2"



async def _prepare_event_without_schedule(event_key: str = "2024noschedule") -> FRCEvent:
    async with AsyncSessionLocal() as session:
        event = FRCEvent(
            event_key=event_key,
            event_name="No Schedule Event",
            short_name="NoSchedule",
            year=2024,
            week=3,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event


def test_public_match_schedule_returns_empty_list_when_no_matches(setup_database):
    event = asyncio.run(_prepare_event_without_schedule())

    with TestClient(app) as client:
        response = client.get(f"/public/matchSchedule/{event.event_key}")

    assert response.status_code == 200
    assert response.json() == []


def test_public_match_schedule_fetches_adhoc_when_db_empty(monkeypatch, setup_database):
    event = asyncio.run(_prepare_event_without_schedule("2024noscheduleadhoc"))

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> list[dict[str, Any]]:
            return [
                {
                    "comp_level": "qm",
                    "match_number": 1,
                    "alliances": {
                        "red": {"team_keys": ["frc111", "frc222", "frc333"]},
                        "blue": {"team_keys": ["frc444", "frc555", "frc666"]},
                    },
                }
            ]

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str, headers: dict[str, str]):
            assert url.endswith(f"/event/{event.event_key}/matches/simple")
            assert "X-TBA-Auth-Key" in headers
            return _FakeResponse()

    monkeypatch.setattr(event_service, "TBA_API_KEY", "test-api-key")
    monkeypatch.setattr(event_service.httpx, "AsyncClient", _FakeAsyncClient)

    with TestClient(app) as client:
        response = client.get(f"/public/matchSchedule/{event.event_key}")

    assert response.status_code == 200
    assert response.json() == [
        {
            "event_key": event.event_key,
            "match_number": 1,
            "match_level": "qm",
            "red1_id": 111,
            "red2_id": 222,
            "red3_id": 333,
            "blue1_id": 444,
            "blue2_id": 555,
            "blue3_id": 666,
        }
    ]
