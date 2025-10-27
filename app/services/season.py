from typing import List

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Season


async def get_seasons(session: AsyncSession) -> List[Season]:
    result = await session.exec(select(Season).order_by(Season.year))
    return result.all()


async def get_season_by_year_or_404(session: AsyncSession, year: int) -> Season:
    statement = select(Season).where(Season.year == year)
    result = await session.execute(statement)
    season = result.scalar_one_or_none()
    if season is None:
        raise HTTPException(status_code=404, detail=f"Season not found for year {year}")
    return season
