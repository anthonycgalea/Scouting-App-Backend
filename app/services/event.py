from fastapi import HTTPException
from sqlmodel import select, delete, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from uuid import UUID
from typing import List

from models import (
    MatchSchedule,
    TeamEvent,
    TeamRecord,
    FRCEvent,
    Organization,
    OrganizationEvent,
)

class MatchScheduleResponse(SQLModel):
    event_key: str
    match_number: int
    match_level: str
    red1_id: int
    red2_id: int
    red3_id: int
    blue1_id: int
    blue2_id: int
    blue3_id: int

class TeamRecordResponse(SQLModel):
    team_number: int
    team_name: str
    location: str

class EventResponse(SQLModel):
    event_key: str
    event_name: str
    short_name: str
    year: int
    week: int



async def get_match_or_404(session: AsyncSession, eventCode: str, matchNumber: int, matchLevel: str) -> MatchScheduleResponse:
    statement = select(MatchSchedule).where(
        MatchSchedule.match_level == matchLevel,
        MatchSchedule.event_key == eventCode,
        MatchSchedule.match_number == int(matchNumber)
    )
    result = await session.execute(statement)
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match

async def get_match_schedule_or_404(session: AsyncSession, eventCode: str) -> List[MatchScheduleResponse]:
    statement = select(MatchSchedule).where(
        MatchSchedule.event_key == eventCode
    )
    result = await session.execute(statement)
    matches = result.scalars().all()  # <-- returns list of MatchSchedule
    if not matches:
        raise HTTPException(status_code=404, detail="No matches found for this event")
    return matches

async def get_team_list_or_404(session: AsyncSession, eventCode: str) -> List[TeamRecordResponse]:
    statement = select(TeamEvent).where(
        TeamEvent.event_key == eventCode
    )
    result = await session.execute(statement)
    teamNumbers = [o.team_number for o in result.scalars().all()]
    teamRecordStatement = select(TeamRecord).where(
        TeamRecord.team_number.in_(teamNumbers)
    )
    teamRecordResult = await session.execute(teamRecordStatement)
    return [TeamRecordResponse(
        team_number=tr.team_number,
        team_name=tr.team_name,
        location=tr.location
    ) for tr in teamRecordResult.scalars().all()]

async def get_event_list_or_404(session: AsyncSession, year: int) -> List[EventResponse]:
    statement = select(FRCEvent).where(
        FRCEvent.year == year
    )
    result = await session.execute(statement)
    return [EventResponse(
        event_key=ev.event_key,
        event_name=ev.event_name,
        short_name=ev.short_name,
        year=ev.year,
        week=ev.week
    ) for ev in result.scalars().all()]


async def get_public_organizations_for_event(session: AsyncSession, eventCode: str) -> List[Organization]:
    statement = (
        select(Organization)
        .join(OrganizationEvent, OrganizationEvent.organization_id == Organization.id)
        .where(
            OrganizationEvent.event_key == eventCode,
            OrganizationEvent.public_data.is_(True),
        )
    )
    result = await session.execute(statement)
    return result.unique().scalars().all()
