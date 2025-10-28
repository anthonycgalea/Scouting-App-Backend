import asyncio
import os

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

from sqlmodel import select

from app.models import (
    FRCEvent,
    Organization,
    PredictionQueue,
    RankingPredictionQueue,
)
from app.services import match_prediction_daemon
from tests.conftest import AsyncSessionLocal


def test_process_prediction_queue_enqueues_ranking_predictions(
    monkeypatch, setup_database
) -> None:
    """Processing match predictions queues ranking prediction jobs once per event/org."""

    monkeypatch.setattr(
        match_prediction_daemon,
        "async_session_factory",
        AsyncSessionLocal,
        raising=False,
    )

    event_key = "2025daemon"

    async def _run_test() -> None:
        async with AsyncSessionLocal() as session:
            event = FRCEvent(
                event_key=event_key,
                event_name="Daemon Event",
                year=2025,
                week=1,
            )
            org_a = Organization(name="Daemon Org A", team_number=111)
            org_b = Organization(name="Daemon Org B", team_number=222)

            session.add_all([event, org_a, org_b])
            await session.commit()
            await session.refresh(org_a)
            await session.refresh(org_b)

            org_a_id = int(org_a.id)
            org_b_id = int(org_b.id)

            session.add_all(
                [
                    PredictionQueue(
                        event_key=event_key,
                        match_number=1,
                        match_level="qm",
                        organization_id=org_a_id,
                    ),
                    PredictionQueue(
                        event_key=event_key,
                        match_number=2,
                        match_level="qm",
                        organization_id=org_b_id,
                    ),
                    RankingPredictionQueue(
                        event_key=event_key,
                        organization_id=org_a_id,
                    ),
                ]
            )
            await session.commit()

        async def fake_simulate_match_prediction(
            session, event_code, match_level, match_number
        ):
            return {
                org_a_id: {"dummy": 1.0},
                org_b_id: {"dummy": 2.0},
            }

        monkeypatch.setattr(
            match_prediction_daemon,
            "simulate_match_prediction",
            fake_simulate_match_prediction,
        )

        work_completed = await match_prediction_daemon.process_prediction_queue()
        assert work_completed is True

        async with AsyncSessionLocal() as session:
            ranking_result = await session.execute(
                select(RankingPredictionQueue).where(
                    RankingPredictionQueue.event_key == event_key
                )
            )
            ranking_entries = {
                (row.event_key, row.organization_id)
                for row in ranking_result.scalars().all()
            }
            assert ranking_entries == {
                (event_key, org_a_id),
                (event_key, org_b_id),
            }

            queue_result = await session.execute(select(PredictionQueue))
            assert queue_result.scalars().all() == []

    asyncio.run(_run_test())
