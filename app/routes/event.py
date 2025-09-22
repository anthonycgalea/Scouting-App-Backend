from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from auth.dependencies import get_current_user
from db.database import get_session
from typing import List

from models import Organization

router = APIRouter(
    prefix="/event",
    tags=["Event"],
)

from services.event import *

@router.get("/{eventCode}/match/{matchLevel}/{matchNumber}", tags=["Scout"])
async def get_single_match(eventCode, matchNumber, matchLevel, session: AsyncSession = Depends(get_session)) -> MatchScheduleResponse:
    return await get_match_or_404(session, eventCode, matchNumber, matchLevel)

@router.get("/{eventCode}/matches")
async def get_match_schedule(eventCode, session: AsyncSession = Depends(get_session)) -> List[MatchScheduleResponse]:
    return await get_match_schedule_or_404(session, eventCode)

@router.get("/{eventCode}/organizations")
async def get_event_organizations(eventCode: str, session: AsyncSession = Depends(get_session)) -> List[Organization]:
    return await get_public_organizations_for_event(session, eventCode)

@router.get("/{eventCode}/teams")
async def get_team_list(eventCode, session: AsyncSession = Depends(get_session)) -> List[TeamRecordResponse]:
    return await get_team_list_or_404(session, eventCode)

@router.get("s/{year}")
async def get_event_list(year: int, session: AsyncSession = Depends(get_session)) -> List[EventResponse]:
    return await get_event_list_or_404(session, year)
