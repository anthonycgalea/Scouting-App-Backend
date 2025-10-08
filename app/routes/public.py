from typing import List

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from db.database import get_session
from models import Season, TeamEvent, TeamRecord
from services.event import (
    EventResponse,
    MatchScheduleResponse,
    get_event_list_or_404,
    get_event_teams_or_404,
    get_match_schedule_or_404,
)
from services.season import get_seasons
from services.team import get_team_records_page

router = APIRouter(prefix="/public", tags=["Public"])


@router.get("/events/{year}", response_model=List[EventResponse])
async def get_public_events(
    year: int, session: AsyncSession = Depends(get_session)
) -> List[EventResponse]:
    return await get_event_list_or_404(session, year)


@router.get(
    "/matchSchedule/{eventCode}", response_model=List[MatchScheduleResponse]
)
async def get_public_match_schedule(
    eventCode: str, session: AsyncSession = Depends(get_session)
) -> List[MatchScheduleResponse]:
    return await get_match_schedule_or_404(session, eventCode)


@router.get("/teams", response_model=List[TeamRecord])
async def get_public_teams(
    page: int = Query(1, ge=1),
    session: AsyncSession = Depends(get_session),
) -> List[TeamRecord]:
    return await get_team_records_page(session, page)


@router.get("/seasons", response_model=List[Season])
async def get_public_seasons(
    session: AsyncSession = Depends(get_session),
) -> List[Season]:
    return await get_seasons(session)


@router.get("/event/teams/{eventCode}", response_model=List[TeamEvent])
async def get_public_event_teams(
    eventCode: str, session: AsyncSession = Depends(get_session)
) -> List[TeamEvent]:
    return await get_event_teams_or_404(session, eventCode)
