from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.database import get_session
from app.models import Season, TeamRecord
from pydantic import BaseModel
from app.services.event import (
    EventResponse,
    MatchScheduleResponse,
    TeamEventResponse,
    get_event_list_or_404,
    get_event_teams_or_404,
    get_match_schedule_or_404,
)
from app.services.season import get_seasons
from app.services.team import get_team_records_page


class PaginationMeta(BaseModel):
    page: int
    currentPage: int
    pageSize: int
    totalItems: int
    totalPages: int
    lastPage: int
    hasNext: bool
    nextPage: Optional[int] = None


class PaginatedTeamRecordsResponse(BaseModel):
    data: List[TeamRecord]
    meta: PaginationMeta

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


@router.get("/teams", response_model=PaginatedTeamRecordsResponse)
async def get_public_teams(
    page: int = Query(1, ge=1),
    session: AsyncSession = Depends(get_session),
) -> PaginatedTeamRecordsResponse:
    teams, meta = await get_team_records_page(session, page)
    return PaginatedTeamRecordsResponse(data=teams, meta=meta)


@router.get("/seasons", response_model=List[Season])
async def get_public_seasons(
    session: AsyncSession = Depends(get_session),
) -> List[Season]:
    return await get_seasons(session)


@router.get("/event/teams/{eventCode}", response_model=List[TeamEventResponse])
async def get_public_event_teams(
    eventCode: str, session: AsyncSession = Depends(get_session)
) -> List[TeamEventResponse]:
    return await get_event_teams_or_404(session, eventCode)
