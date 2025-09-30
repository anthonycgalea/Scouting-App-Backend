import os
from enum import Enum
from datetime import datetime
from typing import Any, Dict, List, Sequence
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlmodel import SQLModel, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import (
    MatchSchedule,
    MatchData2025,
    MatchData2026,
    TBAMatchData,
    TBAMatchData2025,
    Alliance,
    TeamEvent,
    TeamRecord,
    FRCEvent,
    Organization,
    OrganizationEvent,
    UserOrganization,
    UserRole,
    EventRankings,
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

TBA_MATCH_DATA_MODELS_BY_YEAR: Dict[int, type[TBAMatchData]] = {
    2025: TBAMatchData2025,
}

TBA_API_ENDPOINT = os.getenv("TBA_API_ENDPOINT", "https://www.thebluealliance.com/api/v3")
TBA_API_KEY = os.getenv("TBA_API_KEY")

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


class TBAMatchDataRequest(SQLModel):
    matchNumber: int
    matchLevel: str
    teamNumber: int
    alliance: Alliance



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


async def get_tba_match_data_for_match(
    session: AsyncSession,
    user: dict,
    request: TBAMatchDataRequest,
) -> Dict[str, Any]:
    event_key = await get_active_event_key_for_user(session, user)
    event = await get_event_or_404(session, event_key)

    match = await get_match_or_404(
        session,
        event_key,
        request.matchNumber,
        request.matchLevel,
    )

    alliance_teams = (
        (match.red1_id, match.red2_id, match.red3_id)
        if request.alliance == Alliance.RED
        else (match.blue1_id, match.blue2_id, match.blue3_id)
    )

    if request.teamNumber not in alliance_teams:
        raise HTTPException(
            status_code=400,
            detail="Requested team is not part of the specified alliance for this match",
        )

    tba_model = TBA_MATCH_DATA_MODELS_BY_YEAR.get(event.year)
    if tba_model is None:
        raise HTTPException(
            status_code=404,
            detail="TBA match data is not available for this event",
        )

    statement = select(tba_model).where(
        tba_model.event_key == event_key,
        tba_model.match_number == request.matchNumber,
        tba_model.match_level == request.matchLevel,
        tba_model.alliance == request.alliance,
    )
    result = await session.execute(statement)
    record = result.scalars().first()

    if record is None:
        raise HTTPException(status_code=404, detail="TBA match data not found for this match")

    return record.model_dump()


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

    if membership.role == UserRole.GUEST and membership.event_key:
        return membership.event_key

    return active_event.event_key


async def _get_user_membership(
    session: AsyncSession,
    user: dict,
) -> UserOrganization:
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

    return membership


async def _require_lead_or_admin_membership(
    session: AsyncSession,
    user: dict,
) -> UserOrganization:
    membership = await _get_user_membership(session, user)
    if membership.role not in {UserRole.ADMIN, UserRole.LEAD}:
        raise HTTPException(
            status_code=403,
            detail="Only organization leads or team admins can update rankings",
        )
    return membership


def _parse_team_number(team_key: str) -> int:
    if not team_key:
        raise HTTPException(status_code=400, detail="Ranking entry missing team key")

    prefix = "frc"
    if team_key.lower().startswith(prefix):
        team_key = team_key[len(prefix) :]

    try:
        return int(team_key)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid team key in rankings data") from exc


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_sort_order_info(payload: Dict[str, Any]) -> None:
    sort_order_info = payload.get("sort_order_info")
    if isinstance(sort_order_info, list) and len(sort_order_info) >= 3:
        second = sort_order_info[1]
        third = sort_order_info[2]
        if isinstance(second, dict):
            second["name"] = "tiebreaker_1"
        if isinstance(third, dict):
            third["name"] = "tiebreaker2"


async def update_event_rankings_from_tba(
    session: AsyncSession,
    user: dict,
) -> Dict[str, Any]:
    await _require_lead_or_admin_membership(session, user)
    event_key = await get_active_event_key_for_user(session, user)

    if not TBA_API_KEY:
        raise HTTPException(status_code=500, detail="TBA API key is not configured")

    rankings_url = f"{TBA_API_ENDPOINT}/event/{event_key}/rankings"
    headers = {"X-TBA-Auth-Key": TBA_API_KEY, "accept": "application/json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(rankings_url, headers=headers)

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="Failed to retrieve event rankings from The Blue Alliance",
        )

    payload = response.json()
    if not isinstance(payload, dict) or "rankings" not in payload:
        raise HTTPException(status_code=502, detail="Invalid rankings payload from The Blue Alliance")

    rankings: List[Dict[str, Any]] = payload.get("rankings", []) or []

    await session.execute(
        delete(EventRankings).where(EventRankings.event_key == event_key)
    )

    for ranking in rankings:
        team_number = _parse_team_number(ranking.get("team_key"))
        extra_stats = ranking.get("extra_stats") or []
        ranking_points = _coerce_int(extra_stats[0]) if extra_stats else 0
        matches_played = _coerce_int(ranking.get("matches_played"))
        sort_orders = ranking.get("sort_orders") or []
        tiebreaker_1 = _coerce_float(sort_orders[1]) if len(sort_orders) > 1 else 0.0
        tiebreaker_2 = _coerce_float(sort_orders[2]) if len(sort_orders) > 2 else 0.0

        session.add(
            EventRankings(
                event_key=event_key,
                rank=_coerce_int(ranking.get("rank")),
                team_number=team_number,
                ranking_points=ranking_points,
                matches_played=matches_played,
                ranking_tiebreaker_1=tiebreaker_1,
                ranking_tiebreaker_2=tiebreaker_2,
            )
        )

    await session.commit()

    _normalize_sort_order_info(payload)

    return payload
