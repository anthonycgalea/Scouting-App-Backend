from typing import List

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from auth.dependencies import get_current_user
from db.database import get_session
from services.analytics.event_summary import (
    TeamEventSummary,
    get_team_event_summary,
)

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
)


@router.get("/eventSummary/teams", response_model=List[TeamEventSummary])
async def summarize_event_by_team(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_team_event_summary(session, user)
