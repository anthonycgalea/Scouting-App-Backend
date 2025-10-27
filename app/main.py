import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.database import init_db
from app.services.match_prediction_daemon import (
    SLEEP_INTERVAL_SECONDS,
    process_prediction_queue,
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
    while True:
        try:
            await process_prediction_queue()
        except Exception:
            logger.exception("Unhandled error in prediction daemon loop")
        logger.info("Sleeping for %d seconds.", SLEEP_INTERVAL_SECONDS)
        await asyncio.sleep(SLEEP_INTERVAL_SECONDS)


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()
    app.state.prediction_daemon_task = asyncio.create_task(run_prediction_daemon())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("FastAPI application shutting down.")


@app.get("/ping")
def ping():
    return {"message": "pong"}
