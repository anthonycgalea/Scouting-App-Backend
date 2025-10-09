from math import ceil
from typing import Dict, List, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import TeamRecord, UserOrganization
from services.event import (
    MATCH_DATA_MODELS_BY_YEAR,
    get_active_event_key_for_user,
    get_event_or_404,
    get_scouting_alliance_organization_ids,
)


async def get_team_or_404(session: AsyncSession, team_number: int) -> TeamRecord:
    statement = select(TeamRecord).where(TeamRecord.team_number == team_number)
    result = await session.execute(statement)
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


async def get_team_records_page(
    session: AsyncSession,
    page: int,
    page_size: int = 500,
) -> Tuple[List[TeamRecord], Dict[str, int | bool | None]]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be greater than 0")

    total_result = await session.execute(
        select(func.count()).select_from(TeamRecord)
    )
    total_records = total_result.scalar_one()

    total_pages = ceil(total_records / page_size) if total_records else 0

    if total_pages and page > total_pages:
        raise HTTPException(status_code=404, detail="No teams found for this page")

    statement = (
        select(TeamRecord)
        .order_by(TeamRecord.team_number)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(statement)
    teams = result.scalars().all()
    if not teams and page != 1:
        raise HTTPException(status_code=404, detail="No teams found for this page")

    has_next = total_pages != 0 and page < total_pages

    meta: Dict[str, int | bool | None] = {
        "page": page,
        "currentPage": page,
        "pageSize": page_size,
        "totalItems": total_records,
        "totalPages": total_pages,
        "lastPage": total_pages,
        "hasNext": has_next,
        "nextPage": page + 1 if has_next else None,
    }

    return teams, meta


async def get_match_data_for_team_at_active_event(
    session: AsyncSession,
    team_number: int,
    user: dict,
):
    event_key = await get_active_event_key_for_user(session, user)
    event = await get_event_or_404(session, event_key)

    membership_id = user.get("user_org")
    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    match_model = MATCH_DATA_MODELS_BY_YEAR.get(event.year)
    if match_model is None:
        raise HTTPException(status_code=404, detail="Match data is not available for this event")

    alliance_organization_ids = list(
        await get_scouting_alliance_organization_ids(
            session, event_key, membership.organization_id
        )
    )

    statement = select(match_model).where(
        match_model.team_number == team_number,
        match_model.event_key == event_key,
        match_model.organization_id.in_(alliance_organization_ids),
    )
    result = await session.execute(statement)
    return result.scalars().all()
