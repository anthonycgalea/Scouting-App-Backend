from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from db.database import get_session
from services.team import get_team_or_404

router = APIRouter(
    prefix="/teams",
    tags=["Team"],
)


@router.get("/{teamNumber}/info")
async def get_team_info(teamNumber: int, session: AsyncSession = Depends(get_session)):
    return await get_team_or_404(session, teamNumber)
