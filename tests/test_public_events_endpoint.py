import asyncio
import os

from fastapi.testclient import TestClient

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

from app.main import app
from app.models import FRCEvent
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



async def _prepare_event_without_schedule() -> FRCEvent:
    async with AsyncSessionLocal() as session:
        event = FRCEvent(
            event_key="2024noschedule",
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
