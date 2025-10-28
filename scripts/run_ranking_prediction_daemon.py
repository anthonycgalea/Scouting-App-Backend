from __future__ import annotations

import asyncio
import logging

from app.db.database import init_db
from app.logging_config import configure_logging
from app.services.ranking_prediction_daemon import (
    SLEEP_INTERVAL_SECONDS,
    process_ranking_prediction_queue,
)

configure_logging()
logger = logging.getLogger(__name__)


async def _daemon_loop() -> None:
    """Continuously process queued ranking prediction jobs."""

    logger.info("Ranking prediction daemon started.")

    try:
        while True:
            try:
                await process_ranking_prediction_queue()
            except Exception:
                logger.exception("Unhandled error in ranking prediction daemon loop")

            logger.info("Sleeping for %d seconds.", SLEEP_INTERVAL_SECONDS)
            await asyncio.sleep(SLEEP_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Ranking prediction daemon cancelled; shutting down.")
        raise


async def main() -> None:
    """Initialise application resources and run the daemon loop."""

    await init_db()
    await _daemon_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Ranking prediction daemon interrupted; exiting.")
