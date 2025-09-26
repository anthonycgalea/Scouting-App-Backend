from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import TeamRecord, UserOrganization
from services.event import (
    MATCH_DATA_MODELS_BY_YEAR,
    get_active_event_key_for_user,
    get_event_or_404,
)


async def get_team_or_404(session: AsyncSession, team_number: int) -> TeamRecord:
    statement = select(TeamRecord).where(TeamRecord.team_number == team_number)
    result = await session.execute(statement)
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


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

    statement = select(match_model).where(
        match_model.team_number == team_number,
        match_model.event_key == event_key,
        match_model.organization_id == membership.organization_id,
    )
    result = await session.execute(statement)
    return result.scalars().all()
