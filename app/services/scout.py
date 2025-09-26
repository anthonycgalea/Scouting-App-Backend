import os
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple, Callable

import httpx
from fastapi import HTTPException
from sqlalchemy import and_
from sqlmodel import SQLModel, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession
from uuid import UUID

from models import (
    DataValidation,
    MatchData,
    MatchData2025,
    MatchData2026,
    MatchSchedule,
    TBAMatchData,
    TBAMatchData2025,
    User,
    UserOrganization,
    ValidationStatus,
    Alliance,
)
from models.tba_match_data_2025 import Endgame2025 as TBAEndgame2025

from services.event import (
    MATCH_DATA_MODELS_BY_YEAR,
    get_active_event_key_for_user,
    get_event_or_404,
)

TBA_API_BASE_URL = "https://www.thebluealliance.com/api/v3"
TBA_API_KEY_ENV_VAR = "TBA_API_KEY"

TBA_MATCH_DATA_MODELS_BY_YEAR: Dict[int, type[TBAMatchData]] = {
    2025: TBAMatchData2025,
}

TBA_BREAKDOWN_PARSERS_BY_YEAR: Dict[int, Callable[[Optional[Dict[str, Any]]], Dict[str, Any]]] = {}


def _extract_nested_row_count(row_data: Optional[Dict[str, Any]], key: str) -> int:
    if isinstance(row_data, dict) and key in row_data:
        return int(row_data.get(key) or 0)
    return 0


def _extract_reef_counts(reef_data: Optional[Dict[str, Any]]) -> Tuple[int, int, int, int]:
    if not isinstance(reef_data, dict):
        return 0, 0, 0, 0

    direct_top = int(reef_data.get("tba_topRowCount") or 0)
    direct_mid = int(reef_data.get("tba_midRowCount") or 0)
    direct_bot = int(reef_data.get("tba_botRowCount") or 0)

    top_row = _extract_nested_row_count(reef_data.get("topRow"), "tba_rowCount")
    mid_row = _extract_nested_row_count(reef_data.get("midRow"), "tba_rowCount")
    bot_row = _extract_nested_row_count(reef_data.get("botRow"), "tba_rowCount")

    top = direct_top or top_row
    mid = direct_mid or mid_row
    bot = direct_bot or bot_row
    trough = int(reef_data.get("trough") or 0)
    return top, mid, bot, trough


def _map_endgame_status_2025(statuses: Iterable[Optional[str]]) -> TBAEndgame2025:
    priority = (
        ("deepcage", TBAEndgame2025.DEEP),
        ("shallowcage", TBAEndgame2025.SHALLOW),
        ("parked", TBAEndgame2025.PARK),
    )

    normalized = [status.lower() for status in statuses if isinstance(status, str)]
    for keyword, mapped in priority:
        if any(keyword == value for value in normalized):
            return mapped
    return TBAEndgame2025.NONE


def _parse_2025_breakdown(breakdown: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    auto_top, auto_mid, auto_bot, auto_trough = _extract_reef_counts(
        (breakdown or {}).get("autoReef")
    )
    tele_top, tele_mid, tele_bot, tele_trough = _extract_reef_counts(
        (breakdown or {}).get("teleopReef")
    )

    net = int((breakdown or {}).get("netAlgaeCount") or 0)
    processor = int((breakdown or {}).get("wallAlgaeCount") or 0)
    endgame = _map_endgame_status_2025(
        [
            (breakdown or {}).get("endGameRobot1"),
            (breakdown or {}).get("endGameRobot2"),
            (breakdown or {}).get("endGameRobot3"),
        ]
    )

    return {
        "al4c": auto_top,
        "al3c": auto_mid,
        "al2c": auto_bot,
        "al1c": auto_trough,
        "tl4c": tele_top,
        "tl3c": tele_mid,
        "tl2c": tele_bot,
        "tl1c": tele_trough,
        "net": net,
        "processor": processor,
        "endgame": endgame,
    }


TBA_BREAKDOWN_PARSERS_BY_YEAR[2025] = _parse_2025_breakdown


def _parse_tba_breakdown(event_year: int, breakdown: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    parser = TBA_BREAKDOWN_PARSERS_BY_YEAR.get(event_year)
    if parser is None:
        raise HTTPException(
            status_code=404,
            detail="TBA match data is not supported for this event year",
        )

    return parser(breakdown)


class DataValidationFilterRequest(SQLModel):
    matchNumber: Optional[int] = None
    matchLevel: Optional[str] = None
    teamNumber: Optional[int] = None


class DataValidationUpdateRequest(SQLModel):
    matchNumber: int
    matchLevel: str
    teamNumber: int
    userId: UUID
    validationStatus: ValidationStatus
    notes: Optional[str] = None


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


async def batch_update_data_validations(
    session: AsyncSession,
    user: dict,
    updates: List[DataValidationUpdateRequest],
) -> List[DataValidation]:
    if not updates:
        return []

    event_key = await get_active_event_key_for_user(session, user)

    membership_id = user.get("user_org")
    if membership_id is None:
        raise HTTPException(status_code=404, detail="User is not logged into an organization")

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    updated_records: List[DataValidation] = []

    for update in updates:
        statement = select(DataValidation).where(
            DataValidation.event_key == event_key,
            DataValidation.organization_id == membership.organization_id,
            DataValidation.match_number == update.matchNumber,
            DataValidation.match_level == update.matchLevel,
            DataValidation.team_number == update.teamNumber,
            DataValidation.user_id == update.userId,
        )

        result = await session.execute(statement)
        record = result.scalars().first()

        if record is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Data validation record not found for "
                    f"match {update.matchNumber} {update.matchLevel} "
                    f"team {update.teamNumber}"
                ),
            )

        record.validation_status = update.validationStatus
        if update.notes is not None:
            record.notes = update.notes

        session.add(record)
        updated_records.append(record)

    await session.commit()

    for record in updated_records:
        await session.refresh(record)

    return updated_records

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


async def update_tba_match_data_for_pending_alliances(
    session: AsyncSession,
    user: dict,
) -> Dict[str, Any]:
    event_key = await get_active_event_key_for_user(session, user)
    event = await get_event_or_404(session, event_key)

    membership_id = user.get("user_org")
    if membership_id is None:
        raise HTTPException(status_code=404, detail="User is not logged into an organization")

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    organization_id = membership.organization_id

    tba_model = TBA_MATCH_DATA_MODELS_BY_YEAR.get(event.year)
    if tba_model is None:
        raise HTTPException(status_code=404, detail="TBA match data is not available for this event year")

    api_key = os.getenv(TBA_API_KEY_ENV_VAR)
    if not api_key:
        raise HTTPException(status_code=500, detail="TBA API key is not configured")

    schedule_statement = select(MatchSchedule).where(MatchSchedule.event_key == event_key)
    schedule_result = await session.execute(schedule_statement)
    match_schedules = schedule_result.scalars().all()

    if not match_schedules:
        return {"updated_matches": 0, "updated_alliances": 0, "updated_validations": 0}

    pending_statement = select(DataValidation).where(
        DataValidation.event_key == event_key,
        DataValidation.organization_id == organization_id,
        DataValidation.validation_status == ValidationStatus.PENDING,
    )
    pending_result = await session.execute(pending_statement)
    pending_records = pending_result.scalars().all()

    if not pending_records:
        return {"updated_matches": 0, "updated_alliances": 0, "updated_validations": 0}

    pending_by_team: Dict[Tuple[str, int, int], List[DataValidation]] = defaultdict(list)
    for record in pending_records:
        key = (record.match_level, record.match_number, record.team_number)
        pending_by_team[key].append(record)

    alliances_to_process: Dict[str, Dict[str, Any]] = {}
    for schedule in match_schedules:
        alliances = (
            (Alliance.RED, [schedule.red1_id, schedule.red2_id, schedule.red3_id]),
            (Alliance.BLUE, [schedule.blue1_id, schedule.blue2_id, schedule.blue3_id]),
        )

        for alliance, teams in alliances:
            alliance_validations: List[DataValidation] = []
            for team in teams:
                team_records = pending_by_team.get((schedule.match_level, schedule.match_number, team))
                if not team_records:
                    break
                alliance_validations.extend(team_records)
            else:
                match_key = f"{event_key}_{schedule.match_level}{schedule.match_number}"
                match_payload = alliances_to_process.setdefault(
                    match_key,
                    {
                        "match_number": schedule.match_number,
                        "match_level": schedule.match_level,
                        "alliances": [],
                    },
                )
                match_payload["alliances"].append(
                    {
                        "alliance": alliance,
                        "teams": teams,
                        "validations": alliance_validations,
                    }
                )

    if not alliances_to_process:
        return {"updated_matches": 0, "updated_alliances": 0, "updated_validations": 0}

    headers = {"X-TBA-Auth-Key": api_key, "accept": "application/json"}
    updated_alliances = 0
    validations_to_update: Dict[
        Tuple[str, str, int, int, UUID, int],
        DataValidation,
    ] = {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for match_key, match_payload in alliances_to_process.items():
            response = await client.get(
                f"{TBA_API_BASE_URL}/match/{match_key}", headers=headers
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to fetch TBA match data for {match_key}",
                )

            match_data = response.json()
            score_breakdown = match_data.get("score_breakdown") or {}

            for alliance_payload in match_payload["alliances"]:
                alliance_enum: Alliance = alliance_payload["alliance"]
                color_key = alliance_enum.value.lower()
                alliance_breakdown = score_breakdown.get(color_key)
                parsed = _parse_tba_breakdown(event.year, alliance_breakdown)

                statement = select(tba_model).where(
                    tba_model.event_key == event_key,
                    tba_model.match_number == match_payload["match_number"],
                    tba_model.match_level == match_payload["match_level"],
                    tba_model.alliance == alliance_enum,
                )
                result = await session.execute(statement)
                record = result.scalars().first()

                if record is None:
                    record = tba_model(
                        event_key=event_key,
                        match_number=match_payload["match_number"],
                        match_level=match_payload["match_level"],
                        alliance=alliance_enum,
                    )

                for field_name, value in parsed.items():
                    setattr(record, field_name, value)

                session.add(record)
                updated_alliances += 1

                for validation in alliance_payload["validations"]:
                    validation.validation_status = ValidationStatus.NEEDS_REVIEW
                    session.add(validation)
                    validation_key = (
                        validation.event_key,
                        validation.match_level,
                        validation.match_number,
                        validation.team_number,
                        validation.user_id,
                        validation.organization_id,
                    )
                    validations_to_update[validation_key] = validation

    await session.commit()

    return {
        "updated_matches": len(alliances_to_process),
        "updated_alliances": updated_alliances,
        "updated_validations": len(validations_to_update),
    }


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
