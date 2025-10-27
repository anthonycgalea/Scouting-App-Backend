"""Utilities for processing queued match predictions."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Iterable, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.db.database import async_session_factory
from app.models import PredictionQueue
from app.services.match_prediction import simulate_match_prediction

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SLEEP_INTERVAL_SECONDS = 5 * 60
_DAEMON_LOCK_ID = 42_004_200  # Arbitrary constant that uniquely identifies the daemon lock.


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
        .execution_options(compiled_cache=None) 
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


async def acquire_prediction_daemon_lock() -> Tuple[bool, Optional[AsyncConnection]]:
    """Attempt to acquire a database-backed lock for the daemon.

    Uses PostgreSQL advisory locks so that only one worker process runs
    the prediction daemon. If advisory locks aren't supported, it runs
    without coordination.
    """
    async with async_session_factory() as session:
        connection = await session.connection()
        dialect_name = connection.dialect.name

        if not dialect_name.startswith("postgresql"):
            logger.info(
                "Database dialect '%s' does not support advisory locks; "
                "running prediction daemon without coordination.",
                dialect_name,
            )
            return True, None

        try:
            result = await connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": _DAEMON_LOCK_ID},
            )
            acquired = bool(result.scalar())
            if acquired:
                logger.info("Acquired match prediction daemon advisory lock.")
                # Keep the connection open so lock persists
                return True, connection

            logger.info(
                "Another worker already holds the match prediction daemon advisory lock; "
                "skipping daemon start."
            )
        except SQLAlchemyError:
            logger.exception(
                "Failed to acquire match prediction daemon lock; "
                "daemon will not be started in this worker."
            )

    # If we reach here, lock not acquired or exception occurred
    return False, None


async def release_prediction_daemon_lock(connection: AsyncConnection) -> None:
    """Release the advisory lock acquired for the daemon."""
    try:
        await connection.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": _DAEMON_LOCK_ID},
        )
    except SQLAlchemyError:
        logger.exception("Failed to release match prediction daemon advisory lock.")
    finally:
        await connection.close()


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
    "acquire_prediction_daemon_lock",
    "QueuedMatch",
    "release_prediction_daemon_lock",
    "SLEEP_INTERVAL_SECONDS",
    "process_prediction_queue",
    "session_scope",
]
