import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.database import init_db
from app.services.match_prediction_daemon import (
    SLEEP_INTERVAL_SECONDS,
    acquire_prediction_daemon_lock,
    process_prediction_queue,
    release_prediction_daemon_lock,
)
from app.routes import (
    admin,
    analytics,
    event,
    organizationadmin,
    picklist,
    public,
    scout,
    season,
    team,
    user,
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIRECTORY = os.getenv("LOG_DIRECTORY", "logs")
LOG_FILE_NAME = os.getenv("LOG_FILE_NAME", "server.log")
ERROR_LOG_FILE_NAME = os.getenv("ERROR_LOG_FILE_NAME", "error.log")


def configure_logging() -> None:
    """Configure application logging.

    The configuration ensures that log messages continue to be emitted to the
    console (matching the existing behaviour) while also writing all messages to
    a rotating file log and capturing errors in a dedicated rotating error log.
    The handler setup is only performed once to avoid duplicate log entries
    when the module is imported multiple times (such as when running under a
    reloader).
    """

    root_logger = logging.getLogger()
    already_configured = any(
        getattr(handler, "_scouting_app_logging", False)
        for handler in root_logger.handlers
    )
    if already_configured:
        return

    os.makedirs(LOG_DIRECTORY, exist_ok=True)

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    root_logger.setLevel(LOG_LEVEL)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler._scouting_app_logging = True  # type: ignore[attr-defined]
    root_logger.addHandler(stream_handler)

    log_path = os.path.join(LOG_DIRECTORY, LOG_FILE_NAME)
    file_handler = RotatingFileHandler(log_path, maxBytes=10**6, backupCount=5)
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(formatter)
    file_handler._scouting_app_logging = True  # type: ignore[attr-defined]
    root_logger.addHandler(file_handler)

    error_log_path = os.path.join(LOG_DIRECTORY, ERROR_LOG_FILE_NAME)
    error_handler = RotatingFileHandler(
        error_log_path, maxBytes=10**6, backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    error_handler._scouting_app_logging = True  # type: ignore[attr-defined]
    root_logger.addHandler(error_handler)


configure_logging()

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Scouting App API")

origins = [
    # "http://localhost:5173",
    # "http://localhost:8081",
    "http://api.codystats.com",
    "https://api.codystats.com",
    "http://www.codystats.com",
    "https://www.codystats.com",
    "http://codystats.com",
    "https://codystats.com",

]

app.add_middleware(
    CORSMiddleware,
    # allow_origins=["*"],
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(analytics.router)
app.include_router(user.router)
app.include_router(event.router)
app.include_router(organizationadmin.router)
app.include_router(picklist.router)
app.include_router(scout.router)
app.include_router(team.router)
app.include_router(season.router)
app.include_router(public.router)


async def run_prediction_daemon() -> None:
    logger.info("Starting match prediction daemon")
    try:
        while True:
            try:
                await process_prediction_queue()
            except Exception:
                logger.exception("Unhandled error in prediction daemon loop")
            logger.info("Sleeping for %d seconds.", SLEEP_INTERVAL_SECONDS)
            await asyncio.sleep(SLEEP_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Match prediction daemon cancelled; shutting down.")
        raise


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()
    should_run, lock_connection = await acquire_prediction_daemon_lock()
    app.state.prediction_daemon_lock = lock_connection
    if should_run:
        app.state.prediction_daemon_task = asyncio.create_task(run_prediction_daemon())
    else:
        app.state.prediction_daemon_task = None


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("FastAPI application shutting down.")
    task = getattr(app.state, "prediction_daemon_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    lock_connection = getattr(app.state, "prediction_daemon_lock", None)
    if lock_connection is not None:
        await release_prediction_daemon_lock(lock_connection)


@app.get("/ping")
def ping():
    return {"message": "pong"}
