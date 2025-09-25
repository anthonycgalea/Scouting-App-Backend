from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from auth.dependencies import get_current_user
from db.database import get_session
from typing import List

from models import Organization, FRCEvent

router = APIRouter(
    prefix="/event",
    tags=["Event"],
)

from services.event import *

@router.get("/match/{matchLevel}/{matchNumber}", tags=["Scout"])
async def get_single_match(
    matchNumber: int,
    matchLevel: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> MatchScheduleResponse:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_match_or_404(session, event_code, matchNumber, matchLevel)


@router.get("/matches")
async def get_match_schedule(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> List[MatchScheduleResponse]:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_match_schedule_or_404(session, event_code)


@router.get("/organizations")
async def get_event_organizations(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> List[Organization]:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_public_organizations_for_event(session, event_code)


@router.get("/teams")
async def get_team_list(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> List[TeamRecordResponse]:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_team_list_or_404(session, event_code)


@router.get("/info")
async def get_event_info(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> FRCEvent:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_event_or_404(session, event_code)

@router.get("s/{year}")
async def get_event_list(year: int, session: AsyncSession = Depends(get_session)) -> List[EventResponse]:
    return await get_event_list_or_404(session, year)
