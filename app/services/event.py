from enum import Enum
from datetime import datetime
from typing import Any, Dict, List, Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import SQLModel, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import (
    MatchSchedule,
    MatchData2025,
    MatchData2026,
    TeamEvent,
    TeamRecord,
    FRCEvent,
    Organization,
    OrganizationEvent,
    UserOrganization,
    UserRole,
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


class MatchExportType(str, Enum):
    CSV = "csv"
    JSON = "json"
    XLS = "xls"


class MatchExportRequest(SQLModel):
    file_type: MatchExportType


MATCH_DATA_MODELS_BY_YEAR = {
    2025: MatchData2025,
    2026: MatchData2026,
}

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


async def get_match_data_for_event_or_404(
    session: AsyncSession,
    eventCode: str,
):
    event = await get_event_or_404(session, eventCode)
    match_model = MATCH_DATA_MODELS_BY_YEAR.get(event.year)
    if match_model is None:
        raise HTTPException(
            status_code=404,
            detail="Match data export is not supported for this event",
        )

    result = await session.execute(select(match_model).where(match_model.event_key == eventCode))
    match_data = result.scalars().all()
    if not match_data:
        raise HTTPException(status_code=404, detail="No match data available to export")
    return match_data


def _get_model_field_order(model: type[SQLModel]) -> List[str]:
    """Return the model fields in the order they are defined."""

    # SQLModel inherits from pydantic, which exposes either ``__fields__`` (v1)
    # or ``model_fields`` (v2).  We support both to be future-proof.
    field_mapping = getattr(model, "model_fields", None)
    if field_mapping is None:
        field_mapping = getattr(model, "__fields__", {})

    return list(field_mapping.keys())


def serialize_match_data_for_export(match_data: Sequence[SQLModel]) -> List[Dict[str, Any]]:
    if not match_data:
        return []

    model = match_data[0].__class__
    excluded_fields = {"user_id", "season", "organization_id", "timestamp"}
    ordered_fields = [
        field_name
        for field_name in _get_model_field_order(model)
        if field_name not in excluded_fields
    ]

    serialized: List[Dict[str, Any]] = []
    for record in match_data:
        row: Dict[str, Any] = {}
        for field_name in ordered_fields:
            value = getattr(record, field_name)
            if isinstance(value, Enum):
                row[field_name] = value.value
            elif isinstance(value, datetime):
                row[field_name] = value.isoformat()
            elif isinstance(value, UUID):
                row[field_name] = str(value)
            else:
                row[field_name] = value
        serialized.append(row)

    return serialized


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

async def get_event_or_404(session: AsyncSession, eventCode: str) -> FRCEvent:
    statement = select(FRCEvent).where(
        FRCEvent.event_key == eventCode
    )
    result = await session.execute(statement)
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


async def get_active_event_key_for_user(
    session: AsyncSession,
    user: dict,
) -> str:
    user_id = user.get("id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    if isinstance(user_id, str):
        try:
            user_id = UUID(user_id)
        except ValueError as exc:  # pragma: no cover - defensive programming
            raise HTTPException(status_code=400, detail="Invalid user identifier") from exc

    membership_id = user.get("user_org")
    if membership_id is None:
        raise HTTPException(status_code=404, detail="User is not logged into an organization")

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    if membership.user_id != user_id:
        raise HTTPException(status_code=403, detail="User does not belong to this organization")

    statement = select(OrganizationEvent).where(
        OrganizationEvent.organization_id == membership.organization_id,
        OrganizationEvent.active == True,  # noqa: E712 - SQLAlchemy boolean comparison
    )
    result = await session.execute(statement)
    active_event = result.scalar_one_or_none()

    if active_event is None:
        if membership.role == UserRole.GUEST and membership.event_key:
            return membership.event_key
        raise HTTPException(
            status_code=404,
            detail="No active event configured for this organization",
        )

    return active_event.event_key
