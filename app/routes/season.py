from typing import List

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.database import get_session
from app.models import Season
from app.services.season import get_seasons

router = APIRouter(tags=["Season"])


@router.get("/seasons", response_model=List[Season])
async def list_seasons(session: AsyncSession = Depends(get_session)) -> List[Season]:
    return await get_seasons(session)
