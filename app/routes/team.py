from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from auth.dependencies import get_current_user
from db.database import get_session
from services.team import (
    get_match_data_for_team_at_active_event,
    get_team_or_404,
)

router = APIRouter(
    prefix="/teams",
    tags=["Team"],
)


@router.get("/{teamNumber}/info")
async def get_team_info(teamNumber: int, session: AsyncSession = Depends(get_session)):
    return await get_team_or_404(session, teamNumber)


@router.get("/{teamNumber}/matchData")
async def get_team_match_data(
    teamNumber: int,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_match_data_for_team_at_active_event(session, teamNumber, user)
