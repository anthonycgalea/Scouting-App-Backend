from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import TeamRecord


async def get_team_or_404(session: AsyncSession, team_number: int) -> TeamRecord:
    statement = select(TeamRecord).where(TeamRecord.team_number == team_number)
    result = await session.execute(statement)
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team