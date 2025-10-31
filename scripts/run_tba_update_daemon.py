"""Standalone runner for the automated TBA update daemon."""

from __future__ import annotations

import asyncio
import logging

from app.db.database import init_db
from app.logging_config import configure_logging
from app.services.tba_update_daemon import (
    SLEEP_INTERVAL_SECONDS,
    process_pending_tba_updates,
)

configure_logging()
logger = logging.getLogger(__name__)


async def _daemon_loop() -> None:
    """Continuously process pending TBA updates."""

    logger.info("TBA update daemon started.")

    try:
        while True:
            try:
                work_completed = await process_pending_tba_updates()
                if work_completed:
                    logger.info("TBA update cycle completed with updates applied.")
                else:
                    logger.info("TBA update cycle completed with no updates required.")
            except Exception:
                logger.exception("Unhandled error in TBA update daemon loop")

            logger.info("Sleeping for %d seconds.", SLEEP_INTERVAL_SECONDS)
            await asyncio.sleep(SLEEP_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("TBA update daemon cancelled; shutting down.")
        raise


async def main() -> None:
    """Initialise application resources and run the daemon loop."""

    await init_db()
    await _daemon_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("TBA update daemon interrupted; exiting.")

