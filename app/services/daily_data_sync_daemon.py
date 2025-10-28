"""Utilities for performing daily synchronisation with external services."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Dict, List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Season
from app.services.tba_sync import import_event_registration, update_team_list

logger = logging.getLogger(__name__)

RUN_HOUR_LOCAL = 7
SLEEP_INTERVAL_SECONDS = 45


async def perform_daily_sync(session: AsyncSession) -> Dict[str, object]:
    """Execute the full daily data synchronisation workflow."""

    logger.info("Starting daily synchronisation run.")

    team_result = await update_team_list(session)

    seasons_statement = select(Season).where(Season.active.is_(True))
    seasons_result = await session.exec(seasons_statement)
    active_seasons: List[Season] = seasons_result.all()

    logger.info("Found %d active seasons for registration sync.", len(active_seasons))

    event_results: List[Dict[str, object]] = []
    for season in active_seasons:
        logger.info("Syncing registrations for season %s (%s).", season.id, season.year)
        result = await import_event_registration(season.year, session)
        event_results.append({"season_id": season.id, **result})

        if result.get("status") != "success":
            logger.warning(
                "Event registration import for year %s completed with status %s.",
                season.year,
                result.get("status"),
            )

    logger.info("Daily synchronisation run finished.")

    return {"teams": team_result, "events": event_results}


def should_run_sync(now: datetime, last_run_date: date | None) -> bool:
    """Return ``True`` when the sync should execute for the current day."""

    if now.hour != RUN_HOUR_LOCAL:
        return False

    if last_run_date is None:
        return True

    return last_run_date != now.date()
