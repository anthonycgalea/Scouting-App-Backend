"""Utilities for processing queued match predictions."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Iterable

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session_factory
from app.models import PredictionQueue, RankingPredictionQueue
from app.services.match_prediction import simulate_match_prediction

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SLEEP_INTERVAL_SECONDS = 5 * 60


@dataclass(frozen=True)
class QueuedMatch:
    """Representation of a queued match prediction job."""

    event_key: str
    match_level: str
    match_number: int


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional scope around a series of operations."""
    session: AsyncSession = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


async def _load_queued_matches(session: AsyncSession) -> Iterable[QueuedMatch]:
    result = await session.execute(
        select(
            PredictionQueue.event_key,
            PredictionQueue.match_level,
            PredictionQueue.match_number,
        )
        .distinct()
        .order_by(PredictionQueue.match_number.asc())
    )
    rows = result.all()
    return [
        QueuedMatch(
            event_key=event_key,
            match_level=match_level,
            match_number=match_number,
        )
        for event_key, match_level, match_number in rows
    ]


async def _mark_match_complete(session: AsyncSession, match: QueuedMatch) -> None:
    await session.execute(
        delete(PredictionQueue).where(
            PredictionQueue.event_key == match.event_key,
            PredictionQueue.match_level == match.match_level,
            PredictionQueue.match_number == match.match_number,
        )
    )
    await session.commit()


async def _enqueue_ranking_predictions(
    session: AsyncSession,
    *,
    event_key: str,
    organization_ids: Iterable[int],
) -> None:
    """Queue ranking predictions for organizations impacted by match simulations."""

    unique_org_ids = {
        int(org_id)
        for org_id in organization_ids
        if org_id is not None
    }

    if not unique_org_ids:
        return

    existing_statement = select(RankingPredictionQueue.organization_id).where(
        RankingPredictionQueue.event_key == event_key,
        RankingPredictionQueue.organization_id.in_(list(unique_org_ids)),
    )
    existing_result = await session.execute(existing_statement)
    existing_org_ids = set(existing_result.scalars().all())

    missing_org_ids = unique_org_ids - existing_org_ids
    if not missing_org_ids:
        return

    session.add_all(
        RankingPredictionQueue(event_key=event_key, organization_id=org_id)
        for org_id in missing_org_ids
    )


async def process_prediction_queue() -> bool:
    """Process all queued matches once.

    Returns ``True`` if any work was completed.
    """
    async with session_scope() as session:
        matches = await _load_queued_matches(session)
        if not matches:
            logger.info("No matches in prediction queue.")
            return False

        logger.info("Processing %d queued matches.", len(matches))

        work_completed = False
        for match in matches:
            try:
                logger.info(
                    "Running prediction for %s match %s #%s",
                    match.event_key,
                    match.match_level,
                    match.match_number,
                )
                results = await simulate_match_prediction(
                    session,
                    match.event_key,
                    match.match_level,
                    match.match_number,
                )
                await _enqueue_ranking_predictions(
                    session,
                    event_key=match.event_key,
                    organization_ids=(results or {}).keys(),
                )
                await _mark_match_complete(session, match)
                work_completed = True
            except HTTPException as exc:
                logger.warning(
                    "Prediction failed for %s %s #%s: %s",
                    match.event_key,
                    match.match_level,
                    match.match_number,
                    exc.detail,
                )
                await session.rollback()
            except SQLAlchemyError:
                logger.exception(
                    "Database error while processing %s %s #%s",
                    match.event_key,
                    match.match_level,
                    match.match_number,
                )
                await session.rollback()
            except Exception:
                logger.exception(
                    "Unexpected error while processing %s %s #%s",
                    match.event_key,
                    match.match_level,
                    match.match_number,
                )
                await session.rollback()
        return work_completed


__all__ = [
    "QueuedMatch",
    "SLEEP_INTERVAL_SECONDS",
    "process_prediction_queue",
    "session_scope",
]
