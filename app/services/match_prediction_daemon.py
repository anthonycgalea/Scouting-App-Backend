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
from app.models import PredictionQueue
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
                await simulate_match_prediction(
                    session,
                    match.event_key,
                    match.match_level,
                    match.match_number,
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
