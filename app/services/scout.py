from fastapi import HTTPException
from sqlalchemy import and_
from sqlmodel import select, delete, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from uuid import UUID
from typing import List, Optional

from models import (
    DataValidation,
    MatchData,
    MatchData2025,
    MatchData2026,
    UserOrganization,
    User,
    Organization
)

from services.event import (
    MATCH_DATA_MODELS_BY_YEAR,
    get_active_event_key_for_user,
    get_event_or_404,
)


class DataValidationFilterRequest(SQLModel):
    matchNumber: Optional[int] = None
    matchLevel: Optional[str] = None
    teamNumber: Optional[int] = None


async def get_data_validations_for_active_event(
    session: AsyncSession,
    user: dict,
    filters: Optional[DataValidationFilterRequest] = None,
) -> List[DataValidation]:
    event_key = await get_active_event_key_for_user(session, user)

    membership_id = user.get("user_org")
    if membership_id is None:
        raise HTTPException(status_code=404, detail="User is not logged into an organization")

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    statement = select(DataValidation).where(
        DataValidation.event_key == event_key,
        DataValidation.organization_id == membership.organization_id,
    )

    event = None

    if filters:
        if filters.matchNumber is not None:
            statement = statement.where(DataValidation.match_number == filters.matchNumber)
        if filters.matchLevel:
            statement = statement.where(DataValidation.match_level == filters.matchLevel)
        if filters.teamNumber is not None:
            if event is None:
                event = await get_event_or_404(session, event_key)

            match_model = MATCH_DATA_MODELS_BY_YEAR.get(event.year)
            if match_model is None:
                raise HTTPException(status_code=404, detail="Match data is not available for this event")

            join_condition = and_(
                match_model.event_key == DataValidation.event_key,
                match_model.match_number == DataValidation.match_number,
                match_model.match_level == DataValidation.match_level,
                match_model.organization_id == DataValidation.organization_id,
            )
            statement = (
                statement.join(match_model, join_condition)
                .where(match_model.team_number == filters.teamNumber)
            )

    result = await session.execute(statement)
    return result.unique().scalars().all()

class ScoutMatchFilterRequest(SQLModel):
    matchNumber: Optional[int] = None
    matchLevel: Optional[str] = None
    teamNumber: Optional[int] = None


async def get_already_scouted_matches(
    session: AsyncSession,
    user: dict,
    filters: Optional[ScoutMatchFilterRequest] = None,
):
    event_key = await get_active_event_key_for_user(session, user)
    event = await get_event_or_404(session, event_key)

    membership_id = user.get("user_org")
    if membership_id is None:
        raise HTTPException(status_code=404, detail="User is not logged into an organization")

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    match_model = MATCH_DATA_MODELS_BY_YEAR.get(event.year)
    if match_model is None:
        raise HTTPException(status_code=404, detail="Match data is not available for this event")

    statement = select(match_model).where(
        match_model.event_key == event_key,
        match_model.organization_id == membership.organization_id,
    )

    if filters:
        if filters.matchNumber is not None:
            statement = statement.where(match_model.match_number == filters.matchNumber)
        if filters.matchLevel:
            statement = statement.where(match_model.match_level == filters.matchLevel)
        if filters.teamNumber is not None:
            statement = statement.where(match_model.team_number == filters.teamNumber)

    result = await session.execute(statement)
    return result.scalars().all()

async def batch_submit_match(session: AsyncSession, matches: List[MatchData], user: User):
    for match in matches:
        submit_scouted_match(session, match, user)

async def batch_update_match(session: AsyncSession, matches: List[MatchData], user: User):
    for match in matches:
        update_scouted_match(session, match, user)

async def update_scouted_match(session: AsyncSession, match: MatchData, user: User):
    #check if user is part of organization specified in match.organization_id

    #if user is guest, verify event code

    #if valid, go to switch for match submission
    if (match.season == 1): #2025 REEFSCAPE
        await update_2025_match(session, MatchData2025(match), user)
    elif (match.season == 2): #2026 REBUILT
        await update_2026_match(session, MatchData2026(match), user)


async def submit_scouted_match(session: AsyncSession, match: MatchData, user: User):
    #check if user is part of organization specified in match.organization_id

    #if user is guest, verify event code

    #if valid, go to switch for match submission
    if (match.season == 1): #2025 REEFSCAPE
        await submit_2025_match(session, MatchData2025(match), user)
    elif (match.season == 2): #2026 REBUILT
        await submit_2026_match(session, MatchData2026(match), user)


async def submit_2025_match(session: AsyncSession, match: MatchData2025, user: User) -> None:
    pass

async def update_2025_match(session: AsyncSession, match: MatchData2025, user: User) -> None:
    pass

async def submit_2026_match(session: AsyncSession, match: MatchData2026, user: User) -> None:
    pass

async def update_2026_match(session: AsyncSession, match: MatchData2026, user: User) -> None:
    pass
