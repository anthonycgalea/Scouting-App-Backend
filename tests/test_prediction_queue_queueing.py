import pytest
from sqlmodel import select

from app.models import FRCEvent, Organization, PredictionQueue
from app.routes.organizationadmin import _enqueue_matches_for_prediction_queue
from tests.conftest import AsyncSessionLocal


@pytest.mark.asyncio
async def test_enqueue_matches_for_prediction_queue_adds_new_matches(setup_database):
    async with AsyncSessionLocal() as session:
        event = FRCEvent(event_key="2025queue", event_name="Queue Event", year=2025, week=1)
        organization = Organization(name="Queue Org", team_number=1234)
        session.add_all([event, organization])
        await session.commit()

        await _enqueue_matches_for_prediction_queue(
            session,
            event_key=event.event_key,
            organization_id=organization.id,
            matches=[(1, "qm"), (2, "qm")],
        )
        await session.commit()

        result = await session.execute(
            select(PredictionQueue).where(
                PredictionQueue.event_key == event.event_key,
                PredictionQueue.organization_id == organization.id,
            )
        )
        queued_matches = {
            (row.match_number, row.match_level)
            for row in result.scalars().all()
        }
        assert queued_matches == {(1, "qm"), (2, "qm")}

        await _enqueue_matches_for_prediction_queue(
            session,
            event_key=event.event_key,
            organization_id=organization.id,
            matches=[(2, "qm"), (3, "qm")],
        )
        await session.commit()

        result = await session.execute(
            select(PredictionQueue).where(
                PredictionQueue.event_key == event.event_key,
                PredictionQueue.organization_id == organization.id,
            )
        )
        queued_matches = {
            (row.match_number, row.match_level)
            for row in result.scalars().all()
        }
        assert queued_matches == {(1, "qm"), (2, "qm"), (3, "qm")}
