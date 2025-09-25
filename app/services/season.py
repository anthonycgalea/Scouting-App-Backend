from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import Season


async def get_seasons(session: AsyncSession) -> List[Season]:
    result = await session.exec(select(Season).order_by(Season.year))
    return result.all()
