"""Standalone runner for the daily data synchronisation daemon."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

from app.db.database import async_session_factory, init_db
from app.logging_config import configure_logging
from app.services.daily_data_sync_daemon import (
    RUN_HOUR_LOCAL,
    SLEEP_INTERVAL_SECONDS,
    perform_daily_sync,
    should_run_sync,
)

configure_logging()
logger = logging.getLogger(__name__)


async def _daemon_loop() -> None:
    """Run the daily sync task around the configured local hour."""

    last_run_date: date | None = None
    logger.info(
        "Daily data sync daemon started; will run when the local hour reaches %02d:00.",
        RUN_HOUR_LOCAL,
    )

    try:
        while True:
            now = datetime.now()

            if should_run_sync(now, last_run_date):
                async with async_session_factory() as session:
                    try:
                        results = await perform_daily_sync(session)
                        logger.info("Daily sync completed: %s", results)
                        last_run_date = now.date()
                    except Exception:
                        logger.exception("Daily sync encountered an unexpected error.")

            await asyncio.sleep(SLEEP_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Daily sync daemon cancelled; shutting down.")
        raise


async def main() -> None:
    """Initialise application resources and run the daemon loop."""

    await init_db()
    await _daemon_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Daily sync daemon interrupted; exiting.")
