import os
from collections import defaultdict
from enum import Enum as PyEnum
from typing import (
    Any,
    Callable,
    Collection,
    Dict,
    Iterable,
    List,
    Literal,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeVar,
    Union,
    cast,
)

import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession
from uuid import UUID

from models import (
    Alliance,
    DataValidation,
    MatchData,
    MatchData2025,
    MatchData2026,
    Prescout2025,
    MatchSchedule,
    PitScout,
    PitScout2025,
    Season,
    SuperScoutData,
    SuperScoutData2025,
    TBAMatchData,
    TBAMatchData2025,
    User,
    UserOrganization,
    ValidationStatus,
)
from models.tba_match_data_2025 import Endgame2025 as TBAEndgame2025

from services.event import (
    MATCH_DATA_MODELS_BY_YEAR,
    get_active_event_key_for_user,
    get_event_or_404,
    get_scouting_alliance_organization_ids,
)
from services.season import get_season_by_year_or_404

TBA_API_BASE_URL = "https://www.thebluealliance.com/api/v3"
TBA_API_KEY_ENV_VAR = "TBA_API_KEY"

MatchDataType = TypeVar("MatchDataType", bound=MatchData)

TBA_MATCH_DATA_MODELS_BY_YEAR: Dict[int, type[TBAMatchData]] = {
    2025: TBAMatchData2025,
}

PIT_SCOUT_MODELS_BY_YEAR: Dict[int, type[PitScout]] = {
    2025: PitScout2025,
}

PRESCOUT_MODELS_BY_YEAR: Dict[int, type[MatchData]] = {
    2025: Prescout2025,
}

SUPERSCOUT_MODELS_BY_YEAR: Dict[int, type[SuperScoutData]] = {
    2025: SuperScoutData2025,
}

SUPERSCOUT_BUTTON_FIELDS_BASE: List[Tuple[str, str]] = [
    ("stopped_moving", "Stopped Moving"),
    ("dead_lt_45_seconds", "Dead < 45 Seconds"),
    ("dead_gt_45_seconds", "Dead > 45 Seconds"),
    ("slow_drive", "Slow Drive"),
    ("fast_drive", "Fast Drive"),
    ("good_driving", "Good Driving"),
    ("bad_driving", "Bad Driving"),
    ("drops_game_pieces", "Drops Game Pieces"),
    ("lots_of_fouls", "Lots of Fouls"),
    ("tipped", "Tipped"),
    ("didnt_move", "Did Not Move"),
    ("broken", "Broken"),
    ("no_show", "No Show"),
    ("dnp", "DNP"),
    ("played_defense", "Played Defense"),
    ("received_defense", "Received Defense"),
    ("yellow_card", "Yellow Card"),
    ("red_card", "Red Card"),
]

SUPERSCOUT_BUTTON_FIELDS_BY_YEAR: Dict[int, List[Tuple[str, str]]] = {
    2025: [
        *SUPERSCOUT_BUTTON_FIELDS_BASE,
        ("floor_algae", "Picks up Algae off Floor"),
        ("floor_coral", "Picks up Coral off Floor"),
        ("holds_both_pieces", "Holds Both Game Pieces"),
    ],
}

TBA_BREAKDOWN_PARSERS_BY_YEAR: Dict[
    int, Callable[[Optional[Dict[str, Any]], Sequence[int]], Dict[str, Any]]
] = {}

_MATCH_SUBMISSION_PAYLOAD_ALIASES: Dict[str, str] = {
    "eventKey": "event_key",
    "matchNumber": "match_number",
    "matchLevel": "match_level",
    "teamNumber": "team_number",
    "seasonId": "season",
    "organizationId": "organization_id",
    "userId": "user_id",
}


class MatchAlreadyExistsError(Exception):
    def __init__(self, existing_match: MatchData) -> None:
        super().__init__("Match data has already been submitted for this match")
        self.existing_match = existing_match


def _get_model_field_names(model: type[SQLModel]) -> List[str]:
    field_mapping = getattr(model, "model_fields", None)
    if field_mapping is None:
        field_mapping = getattr(model, "__fields__", {})

    return list(field_mapping.keys())


def _model_validate(model: type[SQLModel], payload: Dict[str, Any]) -> SQLModel:
    if hasattr(model, "model_validate"):
        return model.model_validate(payload)  # type: ignore[attr-defined]
    return model.parse_obj(payload)  # type: ignore[attr-defined]


def _model_dump(instance: SQLModel) -> Dict[str, Any]:
    if hasattr(instance, "model_dump"):
        data = instance.model_dump()  # type: ignore[attr-defined]
        extra = getattr(instance, "model_extra", None)
        if isinstance(extra, dict):
            data.update(extra)
        return data

    data = instance.dict()  # type: ignore[attr-defined]
    if hasattr(instance, "__dict__"):
        for key, value in instance.__dict__.items():
            if key in data or key.startswith("_"):
                continue
            data[key] = value
    return data


def _coerce_payload(data: Union[SQLModel, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(data, dict):
        return dict(data)

    return _model_dump(data)


def _apply_payload_aliases(
    payload: Dict[str, Any], aliases: Dict[str, str]
) -> Dict[str, Any]:
    normalized = dict(payload)

    for alias, target in aliases.items():
        if alias not in normalized or target in normalized:
            continue

        normalized[target] = normalized.pop(alias)

    return normalized


def _normalize_user_payload(user: Any) -> Dict[str, Any]:
    if isinstance(user, dict):
        return user

    return {
        "id": getattr(user, "id", None),
        "user_org": getattr(user, "logged_in_user_org", None),
    }


async def _prepare_match_update(
    session: AsyncSession,
    user: Any,
    match: MatchData,
) -> Tuple[MatchData, Dict[str, Any], type[MatchData], UserOrganization, MatchData, MatchData]:
    match_payload = _model_dump(match)

    try:
        base_match = cast(MatchData, _model_validate(MatchData, match_payload))
    except ValidationError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=422, detail="Invalid match data payload") from exc

    user_payload = _normalize_user_payload(user)

    event_key = await get_active_event_key_for_user(session, user_payload)

    if base_match.event_key != event_key:
        raise HTTPException(
            status_code=400,
            detail="Match data event does not match the active event for this user",
        )

    membership_id = user_payload.get("user_org")
    if membership_id is None:
        raise HTTPException(status_code=404, detail="User is not logged into an organization")

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    alliance_organization_ids = await get_scouting_alliance_organization_ids(
        session, event_key, membership.organization_id
    )

    if base_match.organization_id not in alliance_organization_ids:
        raise HTTPException(
            status_code=403,
            detail="Match data does not belong to the active organization or its scouting alliances",
        )

    event = await get_event_or_404(session, event_key)
    season = await session.get(Season, base_match.season)
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found for provided match data")

    if season.year != event.year:
        raise HTTPException(
            status_code=400,
            detail="Match data season does not match the active event year",
        )

    match_model = MATCH_DATA_MODELS_BY_YEAR.get(season.year)
    if match_model is None:
        raise HTTPException(
            status_code=404,
            detail="Match data is not available for this event",
        )

    try:
        typed_match = cast(MatchData, _model_validate(match_model, match_payload))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid match data for this event") from exc

    alliance_organization_ids_tuple = tuple(alliance_organization_ids)

    statement = select(match_model).where(
        match_model.event_key == base_match.event_key,
        match_model.match_number == base_match.match_number,
        match_model.match_level == base_match.match_level,
        match_model.team_number == base_match.team_number,
        match_model.user_id == base_match.user_id,
        match_model.organization_id.in_(alliance_organization_ids_tuple),
    )

    result = await session.execute(statement)
    stored_match = result.scalars().first()

    if stored_match is None:
        raise HTTPException(status_code=404, detail="Match data not found for the provided identifiers")

    if getattr(stored_match, "season", None) != base_match.season:
        raise HTTPException(status_code=400, detail="Season mismatch for match data update")

    return (
        base_match,
        match_payload,
        match_model,
        membership,
        typed_match,
        stored_match,
        alliance_organization_ids,
    )


def _apply_match_update(
    stored_match: MatchData,
    match_model: type[MatchData],
    payload: Dict[str, Any],
) -> None:
    valid_fields = set(_get_model_field_names(match_model))
    protected_fields = {
        "event_key",
        "match_number",
        "match_level",
        "team_number",
        "user_id",
        "organization_id",
    }

    for field_name in valid_fields:
        if field_name in protected_fields or field_name in {"timestamp", "notes"}:
            continue
        if field_name in payload:
            setattr(stored_match, field_name, payload[field_name])


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


def _map_match_endgame_to_tba(status: Any) -> TBAEndgame2025:
    if isinstance(status, TBAEndgame2025):
        return status

    if isinstance(status, str):
        normalized = status.strip().upper()
        if normalized in TBAEndgame2025.__members__:
            return TBAEndgame2025[normalized]
        try:
            return TBAEndgame2025(normalized)
        except ValueError:
            return TBAEndgame2025.NONE

    enum_value = getattr(status, "value", None)
    if isinstance(enum_value, str):
        return _map_match_endgame_to_tba(enum_value)

    return TBAEndgame2025.NONE


def _parse_2025_breakdown(
    breakdown: Optional[Dict[str, Any]], teams: Sequence[int]
) -> Dict[str, Any]:
    auto_top, auto_mid, auto_bot, auto_trough = _extract_reef_counts(
        (breakdown or {}).get("autoReef")
    )
    tele_top, tele_mid, tele_bot, tele_trough = _extract_reef_counts(
        (breakdown or {}).get("teleopReef")
    )

    # TBA reports teleop reef counts as the total corals scored by the end of
    # the match (auto + teleop). Remove the auto contribution so that the
    # teleop values represent just the teleop period performance.
    tele_top = max(tele_top - auto_top, 0)
    tele_mid = max(tele_mid - auto_mid, 0)
    tele_bot = max(tele_bot - auto_bot, 0)
    tele_trough = max(tele_trough - auto_trough, 0)

    net = int((breakdown or {}).get("netAlgaeCount") or 0)
    processor = int((breakdown or {}).get("wallAlgaeCount") or 0)

    endgame_values = {}
    for index, _team_number in enumerate(teams, start=1):
        status_key = f"endGameRobot{index}"
        status_value = (breakdown or {}).get(status_key)
        endgame_values[f"bot{index}endgame"] = _map_endgame_status_2025([status_value])

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
        **endgame_values,
    }


TBA_BREAKDOWN_PARSERS_BY_YEAR[2025] = _parse_2025_breakdown


def _parse_tba_breakdown(
    event_year: int, breakdown: Optional[Dict[str, Any]], teams: Sequence[int]
) -> Dict[str, Any]:
    parser = TBA_BREAKDOWN_PARSERS_BY_YEAR.get(event_year)
    if parser is None:
        raise HTTPException(
            status_code=404,
            detail="TBA match data is not supported for this event year",
        )

    return parser(breakdown, teams)


def _combine_2025_match_data(
    records: Sequence[MatchData], teams: Sequence[int]
) -> Optional[Dict[str, Any]]:
    totals = {
        "al4c": 0,
        "al3c": 0,
        "al2c": 0,
        "al1c": 0,
        "tl4c": 0,
        "tl3c": 0,
        "tl2c": 0,
        "tl1c": 0,
        "net": 0,
        "processor": 0,
        "bot1endgame": TBAEndgame2025.NONE,
        "bot2endgame": TBAEndgame2025.NONE,
        "bot3endgame": TBAEndgame2025.NONE,
    }

    for record in records:
        match_record = cast(MatchData2025, record)
        totals["al4c"] += int(getattr(match_record, "al4c", 0) or 0)
        totals["al3c"] += int(getattr(match_record, "al3c", 0) or 0)
        totals["al2c"] += int(getattr(match_record, "al2c", 0) or 0)
        totals["al1c"] += int(getattr(match_record, "al1c", 0) or 0)
        totals["tl4c"] += int(getattr(match_record, "tl4c", 0) or 0)
        totals["tl3c"] += int(getattr(match_record, "tl3c", 0) or 0)
        totals["tl2c"] += int(getattr(match_record, "tl2c", 0) or 0)
        totals["tl1c"] += int(getattr(match_record, "tl1c", 0) or 0)

        totals["net"] += int(getattr(match_record, "aNet", 0) or 0)
        totals["net"] += int(getattr(match_record, "tNet", 0) or 0)
        totals["processor"] += int(getattr(match_record, "aProcessor", 0) or 0)
        totals["processor"] += int(getattr(match_record, "tProcessor", 0) or 0)

    records_by_team: Dict[int, MatchData2025] = {
        int(getattr(record, "team_number", 0)): cast(MatchData2025, record)
        for record in records
    }

    for index, team in enumerate(teams, start=1):
        match_record = records_by_team.get(team)
        if match_record is None:
            return None
        totals[f"bot{index}endgame"] = _map_match_endgame_to_tba(
            getattr(match_record, "endgame", None)
        )

    return totals


COMBINED_MATCH_DATA_AGGREGATORS_BY_YEAR: Dict[
    int, Callable[[Sequence[MatchData], Sequence[int]], Optional[Dict[str, Any]]]
] = {
    2025: _combine_2025_match_data,
}


async def _fetch_match_data_for_validations(
    session: AsyncSession,
    match_model: type[MatchData],
    validations: Sequence[DataValidation],
) -> List[MatchData]:
    filters = []
    for validation in validations:
        if validation.user_id is None:
            return []

        filters.append(
            and_(
                match_model.event_key == validation.event_key,
                match_model.match_number == validation.match_number,
                match_model.match_level == validation.match_level,
                match_model.team_number == validation.team_number,
                match_model.organization_id == validation.organization_id,
                match_model.user_id == validation.user_id,
            )
        )

    if not filters:
        return []

    statement = select(match_model).where(or_(*filters))
    result = await session.execute(statement)
    records = result.scalars().all()

    record_map: Dict[Tuple[int, UUID], MatchData] = {
        (record.team_number, record.user_id): record for record in records
    }

    ordered_records: List[MatchData] = []
    for validation in validations:
        key = (validation.team_number, validation.user_id)
        record = record_map.get(key)
        if record is None:
            return []
        ordered_records.append(record)

    return ordered_records


async def _calculate_combined_match_data(
    session: AsyncSession,
    event_year: int,
    match_model: Optional[type[MatchData]],
    validations: Sequence[DataValidation],
    teams: Sequence[int],
) -> Optional[Dict[str, Any]]:
    if match_model is None:
        return None

    aggregator = COMBINED_MATCH_DATA_AGGREGATORS_BY_YEAR.get(event_year)
    if aggregator is None:
        return None

    match_records = await _fetch_match_data_for_validations(session, match_model, validations)
    if not match_records or len(match_records) != len(validations):
        return None

    return aggregator(match_records, teams)


def _tba_matches_combined_data(
    event_year: int, tba_data: Dict[str, Any], combined_data: Dict[str, Any]
) -> bool:
    ignored_fields_by_year: Dict[int, Set[str]] = {2025: {"net", "processor"}}
    ignored_fields = ignored_fields_by_year.get(event_year, set())

    for field, tba_value in tba_data.items():
        if field in ignored_fields:
            continue

        combined_value = combined_data.get(field)

        if isinstance(tba_value, PyEnum):
            if combined_value != tba_value:
                if (
                    event_year == 2025
                    and field.startswith("bot")
                    and field.endswith("endgame")
                ):
                    combined_enum = combined_value
                    if isinstance(combined_enum, str):
                        try:
                            combined_enum = TBAEndgame2025(combined_enum)
                        except ValueError:
                            combined_enum = None

                    tba_enum = tba_value
                    if isinstance(tba_enum, str):
                        try:
                            tba_enum = TBAEndgame2025(tba_enum)
                        except ValueError:
                            tba_enum = None

                    acceptable = {TBAEndgame2025.PARK, TBAEndgame2025.NONE}
                    if (
                        isinstance(combined_enum, PyEnum)
                        and isinstance(tba_enum, PyEnum)
                        and {combined_enum, tba_enum}.issubset(acceptable)
                    ):
                        continue
                return False
            continue

        if combined_value is None:
            return False

        if int(tba_value or 0) != int(combined_value or 0):
            return False

    return True


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

    alliance_organization_ids = await get_scouting_alliance_organization_ids(
        session, event_key, membership.organization_id
    )
    alliance_organization_ids_tuple = tuple(alliance_organization_ids)

    statement = select(DataValidation).where(
        DataValidation.event_key == event_key,
        DataValidation.organization_id.in_(alliance_organization_ids_tuple),
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

    alliance_organization_ids = await get_scouting_alliance_organization_ids(
        session, event_key, membership.organization_id
    )
    alliance_organization_ids_tuple = tuple(alliance_organization_ids)

    updated_records: List[DataValidation] = []

    for update in updates:
        statement = select(DataValidation).where(
            DataValidation.event_key == event_key,
            DataValidation.organization_id.in_(alliance_organization_ids_tuple),
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


async def update_match_data_and_mark_validation_valid(
    session: AsyncSession,
    user: dict,
    match: MatchData,
) -> DataValidation:
    (
        base_match,
        match_payload,
        match_model,
        membership,
        typed_match,
        stored_match,
        alliance_organization_ids,
    ) = await _prepare_match_update(session, user, match)

    payload = _model_dump(typed_match)
    _apply_match_update(stored_match, match_model, payload)

    session.add(stored_match)

    alliance_organization_ids_tuple = tuple(alliance_organization_ids)

    validation_statement = select(DataValidation).where(
        DataValidation.event_key == base_match.event_key,
        DataValidation.match_number == base_match.match_number,
        DataValidation.match_level == base_match.match_level,
        DataValidation.team_number == base_match.team_number,
        DataValidation.user_id == base_match.user_id,
        DataValidation.organization_id.in_(alliance_organization_ids_tuple),
    )

    validation_result = await session.execute(validation_statement)
    validation = validation_result.scalars().first()

    if validation is None:
        raise HTTPException(
            status_code=404,
            detail="Data validation record not found for this match",
        )

    validation.validation_status = ValidationStatus.VALID
    if "notes" in match_payload:
        validation.notes = base_match.notes or ""
    session.add(validation)

    await session.commit()
    await session.refresh(validation)

    return validation


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

    alliance_organization_ids = await get_scouting_alliance_organization_ids(
        session, event_key, membership.organization_id
    )

    if not alliance_organization_ids:
        return []

    statement = select(match_model).where(
        match_model.event_key == event_key,
        match_model.organization_id.in_(tuple(alliance_organization_ids)),
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


async def get_prescout_records(
    session: AsyncSession,
    user: dict,
    *,
    team_number: Optional[int] = None,
):
    user_payload = _normalize_user_payload(user)

    event_key = await get_active_event_key_for_user(session, user_payload)
    event = await get_event_or_404(session, event_key)

    membership = await _get_user_membership_or_404(session, user_payload)

    prescout_model = PRESCOUT_MODELS_BY_YEAR.get(event.year)
    if prescout_model is None:
        raise HTTPException(
            status_code=404,
            detail="Prescouting is not available for this event",
        )

    alliance_organization_ids = await get_scouting_alliance_organization_ids(
        session, event_key, membership.organization_id
    )

    if not alliance_organization_ids:
        return []

    statement = select(prescout_model).where(
        prescout_model.event_key == event_key,
        prescout_model.organization_id.in_(tuple(alliance_organization_ids)),
    )

    if team_number is not None:
        statement = statement.where(prescout_model.team_number == team_number)

    result = await session.execute(statement)
    return result.scalars().all()


async def get_superscout_records(
    session: AsyncSession,
    user: dict,
    *,
    team_number: Optional[int] = None,
) -> List[SuperScoutData]:
    user_payload = _normalize_user_payload(user)

    event_key = await get_active_event_key_for_user(session, user_payload)
    event = await get_event_or_404(session, event_key)

    membership = await _get_user_membership_or_404(session, user_payload)

    superscout_model = SUPERSCOUT_MODELS_BY_YEAR.get(event.year)
    if superscout_model is None:
        raise HTTPException(
            status_code=404,
            detail="Superscouting is not available for this event",
        )

    alliance_organization_ids = list(
        await get_scouting_alliance_organization_ids(
            session, event_key, membership.organization_id
        )
    )

    statement = select(superscout_model).where(
        superscout_model.event_key == event_key,
        superscout_model.organization_id.in_(alliance_organization_ids),
    )

    if team_number is not None:
        statement = statement.where(superscout_model.team_number == team_number)

    result = await session.execute(statement)
    return result.scalars().all()


async def get_superscouted_match_alliances(
    session: AsyncSession,
    user: dict,
) -> List[Dict[str, Any]]:
    user_payload = _normalize_user_payload(user)

    event_key = await get_active_event_key_for_user(session, user_payload)
    event = await get_event_or_404(session, event_key)

    membership = await _get_user_membership_or_404(session, user_payload)

    superscout_model = SUPERSCOUT_MODELS_BY_YEAR.get(event.year)
    if superscout_model is None:
        raise HTTPException(
            status_code=404,
            detail="Superscouting is not available for this event",
        )

    schedule_statement = select(MatchSchedule).where(
        MatchSchedule.event_key == event_key
    )
    schedule_result = await session.execute(schedule_statement)
    match_schedules = schedule_result.scalars().all()

    if not match_schedules:
        return []

    alliance_organization_ids = list(
        await get_scouting_alliance_organization_ids(
            session, event_key, membership.organization_id
        )
    )

    superscout_statement = select(superscout_model).where(
        superscout_model.event_key == event_key,
        superscout_model.organization_id.in_(alliance_organization_ids),
    )
    superscout_result = await session.execute(superscout_statement)
    superscout_records = superscout_result.scalars().all()

    scouted_by_match: Dict[Tuple[str, int], Set[int]] = defaultdict(set)
    for record in superscout_records:
        scouted_by_match[(record.match_level, record.match_number)].add(
            record.team_number
        )

    match_schedules.sort(key=lambda match: (match.match_level, match.match_number))

    response: List[Dict[str, Any]] = []
    for schedule in match_schedules:
        match_key = (schedule.match_level, schedule.match_number)
        scouted_teams = scouted_by_match.get(match_key, set())

        red_teams = [
            team
            for team in (
                schedule.red1_id,
                schedule.red2_id,
                schedule.red3_id,
            )
            if team is not None
        ]
        blue_teams = [
            team
            for team in (
                schedule.blue1_id,
                schedule.blue2_id,
                schedule.blue3_id,
            )
            if team is not None
        ]

        response.append(
            {
                "eventCode": schedule.event_key,
                "matchLevel": schedule.match_level,
                "matchNumber": schedule.match_number,
                "red": all(team in scouted_teams for team in red_teams),
                "blue": all(team in scouted_teams for team in blue_teams),
            }
        )

    return response


async def get_superscout_field_options(
    session: AsyncSession,
    user: dict,
) -> List[Dict[str, str]]:
    user_payload = _normalize_user_payload(user)

    event_key = await get_active_event_key_for_user(session, user_payload)
    event = await get_event_or_404(session, event_key)

    if SUPERSCOUT_MODELS_BY_YEAR.get(event.year) is None:
        raise HTTPException(
            status_code=404,
            detail="Superscouting is not available for this event",
        )

    field_options = SUPERSCOUT_BUTTON_FIELDS_BY_YEAR.get(
        event.year, SUPERSCOUT_BUTTON_FIELDS_BASE
    )

    return [{"key": key, "label": label} for key, label in field_options]


class PitScoutDeleteRequest(SQLModel):
    team_number: int
    season: Optional[int] = None
    event_key: Optional[str] = None


async def _normalize_user_id(user_payload: Dict[str, Any]) -> UUID:
    user_id = user_payload.get("id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    if isinstance(user_id, UUID):
        return user_id

    try:
        return UUID(str(user_id))
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=400, detail="Invalid user identifier") from exc


async def _get_user_membership_or_404(
    session: AsyncSession, user_payload: Dict[str, Any]
) -> UserOrganization:
    membership_id = user_payload.get("user_org")
    if membership_id is None:
        raise HTTPException(status_code=404, detail="User is not logged into an organization")

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    return membership


def _prepare_match_submission_payload(
    payload: Dict[str, Any],
    *,
    event_key: str,
    season: Season,
    membership: UserOrganization,
    user_id: UUID,
) -> Dict[str, Any]:
    prepared_payload = dict(payload)

    incoming_event_key = prepared_payload.get("event_key")
    if incoming_event_key is not None and incoming_event_key != event_key:
        raise HTTPException(
            status_code=400,
            detail="Match data event does not match the active event for this user",
        )
    prepared_payload["event_key"] = event_key

    incoming_season = prepared_payload.get("season")
    if incoming_season is not None:
        try:
            incoming_season_id = int(incoming_season)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid season provided for match data",
            ) from exc

        if incoming_season_id != season.id:
            raise HTTPException(
                status_code=400,
                detail="Match data season does not match the active event year",
            )
    prepared_payload["season"] = season.id

    if membership.user_id != user_id:
        raise HTTPException(status_code=403, detail="User does not belong to this organization")

    incoming_user_id = _coerce_optional_uuid(prepared_payload.get("user_id"))
    if incoming_user_id is not None and incoming_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Match data user does not match the authenticated user",
        )
    prepared_payload["user_id"] = user_id

    organization_id = membership.organization_id
    incoming_org_id = prepared_payload.get("organization_id")
    if incoming_org_id is not None:
        try:
            incoming_org_id_int = int(incoming_org_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid organization identifier for match data",
            ) from exc

        if incoming_org_id_int != organization_id:
            raise HTTPException(
                status_code=403,
                detail="Match data does not belong to the active organization",
            )
    prepared_payload["organization_id"] = organization_id

    return prepared_payload


def _coerce_optional_uuid(value: Any) -> Optional[UUID]:
    if value is None or isinstance(value, UUID):
        return value

    try:
        return UUID(str(value))
    except (TypeError, ValueError):  # pragma: no cover - defensive guard
        return None


def _get_pit_model_for_event(event_year: int) -> type[PitScout]:
    pit_model = PIT_SCOUT_MODELS_BY_YEAR.get(event_year)
    if pit_model is None:
        raise HTTPException(status_code=404, detail="Pit scouting is not available for this event year")

    return pit_model


async def get_pit_scout_records(
    session: AsyncSession,
    user: Any,
    *,
    team_number: Optional[int] = None,
) -> List[PitScout]:
    user_payload = _normalize_user_payload(user)
    event_key = await get_active_event_key_for_user(session, user_payload)
    event = await get_event_or_404(session, event_key)

    membership = await _get_user_membership_or_404(session, user_payload)

    pit_model = _get_pit_model_for_event(event.year)

    alliance_organization_ids = await get_scouting_alliance_organization_ids(
        session, event_key, membership.organization_id
    )

    if not alliance_organization_ids:
        return []

    statement = select(pit_model).where(
        pit_model.event_key == event_key,
        pit_model.organization_id.in_(tuple(alliance_organization_ids)),
    )

    if team_number is not None:
        statement = statement.where(pit_model.team_number == team_number)

    result = await session.execute(statement)
    return list(result.scalars().all())


async def _prepare_pit_payload(
    session: AsyncSession,
    user_payload: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    allowed_organization_ids: Optional[Collection[int]] = None,
    assign_default_organization_id: bool = True,
) -> tuple[type[PitScout], Season, UUID, UserOrganization, str]:
    event_key = await get_active_event_key_for_user(session, user_payload)

    incoming_event_key = payload.get("event_key")
    if incoming_event_key is not None and incoming_event_key != event_key:
        raise HTTPException(
            status_code=400,
            detail="Pit scouting event does not match the active event for this user",
        )
    payload["event_key"] = event_key

    membership = await _get_user_membership_or_404(session, user_payload)
    user_id = await _normalize_user_id(user_payload)

    if membership.user_id != user_id:
        raise HTTPException(status_code=403, detail="User does not belong to this organization")

    incoming_user_id = _coerce_optional_uuid(payload.get("user_id"))
    if incoming_user_id is not None and incoming_user_id != user_id:
        raise HTTPException(status_code=403, detail="Pit scouting user does not match the authenticated user")

    payload["user_id"] = user_id

    organization_id = membership.organization_id
    allowed_ids: Set[int]
    if allowed_organization_ids is not None:
        allowed_ids = {int(org_id) for org_id in allowed_organization_ids}
        allowed_ids.add(int(organization_id))
    else:
        allowed_ids = {int(organization_id)}

    incoming_org_id = payload.get("organization_id")
    if incoming_org_id is not None:
        try:
            incoming_org_id_int = int(incoming_org_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid organization identifier for pit scouting data") from exc

        if incoming_org_id_int not in allowed_ids:
            raise HTTPException(
                status_code=403,
                detail="Pit scouting data does not belong to the active organization",
            )

        organization_id = incoming_org_id_int

    if assign_default_organization_id:
        payload["organization_id"] = organization_id

    if "team_number" in payload and payload.get("team_number") is not None:
        try:
            payload["team_number"] = int(payload["team_number"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid team number provided for pit scouting data") from exc

    event = await get_event_or_404(session, event_key)

    season_id = payload.get("season")
    if season_id is None:
        season = await get_season_by_year_or_404(session, event.year)
        payload["season"] = season.id
    else:
        season = await session.get(Season, season_id)
        if season is None:
            raise HTTPException(status_code=404, detail="Season not found for provided pit scouting data")

        if season.year != event.year:
            raise HTTPException(
                status_code=400,
                detail="Pit scouting season does not match the active event year",
            )

    pit_model = _get_pit_model_for_event(event.year)

    payload["notes"] = payload.get("notes") or ""

    return pit_model, season, user_id, membership, event_key


async def create_pit_scout_record(
    session: AsyncSession,
    pit: Union[Dict[str, Any], PitScout],
    user: Any,
) -> PitScout:
    payload = _coerce_payload(pit)
    user_payload = _normalize_user_payload(user)

    pit_model, _season, user_id, _membership, event_key = await _prepare_pit_payload(
        session, user_payload, payload
    )

    payload.pop("timestamp", None)

    try:
        typed_pit = cast(PitScout, _model_validate(pit_model, payload))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid pit scouting data for this event") from exc

    statement = select(pit_model).where(
        pit_model.event_key == event_key,
        pit_model.team_number == typed_pit.team_number,
        pit_model.user_id == user_id,
    )

    result = await session.execute(statement)
    if result.scalars().first() is not None:
        raise HTTPException(
            status_code=409,
            detail="Pit scouting data has already been submitted for this team",
        )

    session.add(typed_pit)
    await session.commit()
    await session.refresh(typed_pit)

    return typed_pit


async def update_pit_scout_record(
    session: AsyncSession,
    pit: Union[Dict[str, Any], PitScout],
    user: Any,
) -> PitScout:
    payload = _coerce_payload(pit)
    user_payload = _normalize_user_payload(user)

    event_key = await get_active_event_key_for_user(session, user_payload)
    membership = await _get_user_membership_or_404(session, user_payload)

    alliance_organization_ids = await get_scouting_alliance_organization_ids(
        session, event_key, membership.organization_id
    )

    pit_model, _season, user_id, _membership, prepared_event_key = await _prepare_pit_payload(
        session,
        user_payload,
        payload,
        allowed_organization_ids=alliance_organization_ids,
        assign_default_organization_id=False,
    )

    # ``_prepare_pit_payload`` guarantees the event key aligns with the user's
    # active event. Reuse the normalized value for downstream queries.
    event_key = prepared_event_key

    team_number = payload.get("team_number")
    if team_number is None:
        raise HTTPException(status_code=400, detail="Team number is required to update pit scouting data")

    statement = select(pit_model).where(
        pit_model.event_key == event_key,
        pit_model.team_number == team_number,
        pit_model.organization_id.in_(tuple(alliance_organization_ids)),
    )

    result = await session.execute(statement)
    stored_record = result.scalars().first()

    if stored_record is None:
        raise HTTPException(status_code=404, detail="Pit scouting record not found for this team")

    stored_payload = _model_dump(stored_record)
    merged_payload = {**stored_payload, **payload}
    merged_payload["user_id"] = stored_record.user_id
    merged_payload.pop("organization_id", None)
    merged_payload["organization_id"] = stored_record.organization_id
    merged_payload["notes"] = merged_payload.get("notes") or ""

    try:
        typed_pit = cast(PitScout, _model_validate(pit_model, merged_payload))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid pit scouting data for this event") from exc

    valid_fields = set(_get_model_field_names(pit_model))
    protected_fields = {"event_key", "team_number", "user_id", "organization_id"}

    for field_name in valid_fields:
        if field_name in protected_fields:
            continue
        setattr(stored_record, field_name, getattr(typed_pit, field_name))

    extra_fields = getattr(typed_pit, "model_extra", None)
    if isinstance(extra_fields, dict):
        for field_name, value in extra_fields.items():
            if field_name in protected_fields:
                continue
            setattr(stored_record, field_name, value)

    session.add(stored_record)
    await session.commit()
    await session.refresh(stored_record)

    return stored_record


async def delete_pit_scout_record(
    session: AsyncSession,
    request: PitScoutDeleteRequest,
    user: Any,
) -> None:
    user_payload = _normalize_user_payload(user)
    payload = {
        "season": request.season,
        "event_key": request.event_key,
        "team_number": request.team_number,
    }

    pit_model, _season, user_id, membership, event_key = await _prepare_pit_payload(
        session, user_payload, payload
    )

    team_number = payload.get("team_number")
    if team_number is None:
        raise HTTPException(status_code=400, detail="Team number is required to delete pit scouting data")

    statement = select(pit_model).where(
        pit_model.event_key == event_key,
        pit_model.team_number == team_number,
        pit_model.user_id == user_id,
    )

    result = await session.execute(statement)
    record = result.scalars().first()

    if record is None:
        raise HTTPException(status_code=404, detail="Pit scouting record not found for this team")

    await session.delete(record)
    await session.commit()


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

    alliance_organization_ids = await get_scouting_alliance_organization_ids(
        session, event_key, organization_id
    )
    alliance_organization_ids_tuple = tuple(alliance_organization_ids)

    match_model = MATCH_DATA_MODELS_BY_YEAR.get(event.year)

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
        DataValidation.organization_id.in_(alliance_organization_ids_tuple),
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
                parsed = _parse_tba_breakdown(
                    event.year,
                    alliance_breakdown,
                    alliance_payload["teams"],
                )

                validations: List[DataValidation] = alliance_payload["validations"]
                should_attempt_auto_validate = (
                    len(validations) == len(alliance_payload["teams"])
                    and len({validation.team_number for validation in validations})
                    == len(alliance_payload["teams"])
                )

                combined_data: Optional[Dict[str, Any]] = None
                if should_attempt_auto_validate:
                    combined_data = await _calculate_combined_match_data(
                        session,
                        event.year,
                        match_model,
                        validations,
                        alliance_payload["teams"],
                    )

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

                validations_status = ValidationStatus.NEEDS_REVIEW
                if (
                    combined_data is not None
                    and _tba_matches_combined_data(event.year, parsed, combined_data)
                ):
                    validations_status = ValidationStatus.VALID

                for validation in validations:
                    validation.validation_status = validations_status
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


async def batch_submit_match(
    session: AsyncSession,
    matches: Sequence[Union[MatchData, Dict[str, Any]]],
    user: User,
) -> None:
    for match in matches:
        try:
            await submit_scouted_match(session, match, user)
        except HTTPException as exc:
            if exc.status_code == 304:
                continue
            raise

async def batch_update_match(session: AsyncSession, matches: List[MatchData], user: User):
    for match in matches:
        update_scouted_match(session, match, user)

async def update_scouted_match(session: AsyncSession, match: MatchData, user: User):
    (
        _base_match,
        _payload,
        match_model,
        _membership,
        typed_match,
        stored_match,
        _alliance_organization_ids,
    ) = await _prepare_match_update(session, user, match)

    updated_payload = _model_dump(typed_match)
    _apply_match_update(stored_match, match_model, updated_payload)

    session.add(stored_match)


async def submit_scouted_match(
    session: AsyncSession,
    match: Union[MatchData, Dict[str, Any]],
    user: User,
) -> MatchData:
    payload = _coerce_payload(match)
    payload = _apply_payload_aliases(payload, _MATCH_SUBMISSION_PAYLOAD_ALIASES)
    user_payload = _normalize_user_payload(user)

    event_key = await get_active_event_key_for_user(session, user_payload)
    event = await get_event_or_404(session, event_key)

    match_model = MATCH_DATA_MODELS_BY_YEAR.get(event.year)
    if match_model is None:
        raise HTTPException(status_code=404, detail="Match data is not available for this event")

    season = await get_season_by_year_or_404(session, event.year)
    membership = await _get_user_membership_or_404(session, user_payload)
    user_id = await _normalize_user_id(user_payload)

    prepared_payload = _prepare_match_submission_payload(
        payload,
        event_key=event_key,
        season=season,
        membership=membership,
        user_id=user_id,
    )
    prepared_payload["notes"] = prepared_payload.get("notes") or ""
    prepared_payload.pop("timestamp", None)

    try:
        typed_match = cast(MatchData, _model_validate(match_model, prepared_payload))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid match data for this season") from exc

    try:
        return await _submit_match_for_year(
            session,
            typed_match,
            user,
            expected_year=event.year,
            match_model=match_model,
            duplicate_behavior="skip",
        )
    except MatchAlreadyExistsError as exc:
        raise HTTPException(
            status_code=304,
            detail="Match data has already been submitted for this match",
        ) from exc


async def submit_prescout_record(
    session: AsyncSession,
    prescout: MatchData,
    user: User,
) -> MatchData:
    prescout_payload = _model_dump(prescout)
    try:
        base_prescout = _model_validate(MatchData, prescout_payload)
    except ValidationError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=422, detail="Invalid prescout payload") from exc

    season = await session.get(Season, base_prescout.season)
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found for provided prescout data")

    prescout_model = PRESCOUT_MODELS_BY_YEAR.get(season.year)
    if prescout_model is None:
        raise HTTPException(
            status_code=404,
            detail="Prescouting is not available for this season",
        )

    return await _submit_match_for_year(
        session,
        prescout,
        user,
        expected_year=season.year,
        match_model=prescout_model,
    )


async def submit_superscout_record(
    session: AsyncSession,
    superscout: Union[Dict[str, Any], SuperScoutData],
    user: Any,
) -> SuperScoutData:
    payload = _coerce_payload(superscout)
    user_payload = _normalize_user_payload(user)

    event_key = await get_active_event_key_for_user(session, user_payload)
    incoming_event_key = payload.get("event_key")
    if incoming_event_key is not None and incoming_event_key != event_key:
        raise HTTPException(
            status_code=400,
            detail="Superscout event does not match the active event for this user",
        )
    payload["event_key"] = event_key

    membership = await _get_user_membership_or_404(session, user_payload)
    user_id = await _normalize_user_id(user_payload)

    if membership.user_id != user_id:
        raise HTTPException(status_code=403, detail="User does not belong to this organization")

    incoming_user_id = _coerce_optional_uuid(payload.get("user_id"))
    if incoming_user_id is not None and incoming_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Superscout data user does not match the authenticated user",
        )
    payload["user_id"] = user_id

    organization_id = membership.organization_id
    incoming_org_id = payload.get("organization_id")
    if incoming_org_id is not None:
        try:
            incoming_org_id_int = int(incoming_org_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid organization identifier for superscout data") from exc

        if incoming_org_id_int != organization_id:
            raise HTTPException(
                status_code=403,
                detail="Superscout data does not belong to the active organization",
            )
    payload["organization_id"] = organization_id

    event = await get_event_or_404(session, event_key)

    season = await get_season_by_year_or_404(session, event.year)
    incoming_season = payload.get("season")
    if incoming_season is not None:
        try:
            incoming_season_id = int(incoming_season)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid season provided for superscout data") from exc

        if incoming_season_id != season.id:
            raise HTTPException(
                status_code=400,
                detail="Superscout season does not match the active event year",
            )
    payload["season"] = season.id

    superscout_model = SUPERSCOUT_MODELS_BY_YEAR.get(event.year)
    if superscout_model is None:
        raise HTTPException(
            status_code=404,
            detail="Superscouting is not available for this season",
        )

    payload["notes"] = payload.get("notes") or ""
    payload.pop("timestamp", None)

    try:
        typed_superscout = cast(SuperScoutData, _model_validate(superscout_model, payload))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid superscout data for this season") from exc

    statement = select(superscout_model).where(
        superscout_model.event_key == getattr(typed_superscout, "event_key"),
        superscout_model.match_number == getattr(typed_superscout, "match_number"),
        superscout_model.match_level == getattr(typed_superscout, "match_level"),
        superscout_model.team_number == getattr(typed_superscout, "team_number"),
        superscout_model.user_id == getattr(typed_superscout, "user_id"),
        superscout_model.organization_id == getattr(typed_superscout, "organization_id"),
    )

    result = await session.execute(statement)
    if result.scalars().first() is not None:
        raise HTTPException(
            status_code=409,
            detail="Super scout data has already been submitted for this match",
        )

    session.add(typed_superscout)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Super scout data has already been submitted for this match",
        ) from exc

    await session.refresh(typed_superscout)

    return typed_superscout


async def _submit_match_for_year(
    session: AsyncSession,
    match: MatchData,
    user: User,
    *,
    expected_year: int,
    match_model: type[MatchData],
    duplicate_behavior: Literal["error", "skip"] = "error",
) -> MatchData:
    match_payload = _model_dump(match)
    try:
        base_match = _model_validate(MatchData, match_payload)
    except ValidationError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=422, detail="Invalid match data payload") from exc

    user_id: Optional[UUID] = getattr(user, "id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    if isinstance(user_id, str):
        try:
            user_id = UUID(user_id)
        except ValueError as exc:  # pragma: no cover - defensive programming
            raise HTTPException(status_code=400, detail="Invalid user identifier") from exc

    membership_id = getattr(user, "logged_in_user_org", None)
    if membership_id is None:
        raise HTTPException(status_code=404, detail="User is not logged into an organization")

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    if membership.user_id != user_id:
        raise HTTPException(status_code=403, detail="User does not belong to this organization")

    if base_match.organization_id != membership.organization_id:
        raise HTTPException(
            status_code=403,
            detail="Match data does not belong to the active organization",
        )

    event = await get_event_or_404(session, base_match.event_key)
    if event.year != expected_year:
        raise HTTPException(
            status_code=400,
            detail="Match data event does not match the expected season year",
        )

    season = await session.get(Season, base_match.season)
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found for provided match data")

    if season.year != expected_year:
        raise HTTPException(
            status_code=400,
            detail="Match data season does not match the expected season year",
        )

    match_user_id = getattr(base_match, "user_id", None)
    if match_user_id and match_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Match data user does not match the authenticated user",
        )

    payload = {**match_payload, "user_id": user_id, "organization_id": membership.organization_id}
    payload["notes"] = payload.get("notes") or ""
    payload.pop("timestamp", None)

    try:
        typed_match = cast(MatchData, _model_validate(match_model, payload))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid match data for this season") from exc

    statement = select(match_model).where(
        match_model.event_key == getattr(typed_match, "event_key"),
        match_model.match_number == getattr(typed_match, "match_number"),
        match_model.match_level == getattr(typed_match, "match_level"),
        match_model.team_number == getattr(typed_match, "team_number"),
        match_model.user_id == getattr(typed_match, "user_id"),
        match_model.organization_id == getattr(typed_match, "organization_id"),
    )
    result = await session.execute(statement)
    existing_match = result.scalars().first()
    if existing_match is not None:
        if duplicate_behavior == "skip":
            raise MatchAlreadyExistsError(cast(MatchData, existing_match))
        raise HTTPException(
            status_code=409,
            detail="Match data has already been submitted for this match",
        )

    session.add(typed_match)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Match data has already been submitted for this match",
        ) from exc

    await session.refresh(typed_match)

    return typed_match


async def submit_2025_match(session: AsyncSession, match: MatchData2025, user: User) -> MatchData:
    return await _submit_match_for_year(
        session,
        match,
        user,
        expected_year=2025,
        match_model=MatchData2025,
    )


async def _edit_match_for_year(
    session: AsyncSession,
    match: MatchData,
    user: User,
    *,
    expected_year: int,
    match_model: type[MatchDataType],
) -> MatchDataType:
    match_payload = _model_dump(match)
    try:
        base_match = _model_validate(MatchData, match_payload)
    except ValidationError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=422, detail="Invalid match data payload") from exc

    user_id: Optional[UUID] = getattr(user, "id", None)
    if user_id is None and isinstance(user, dict):
        raw_user_id = user.get("id")
        if raw_user_id is not None:
            user_id = cast(Optional[UUID], raw_user_id)

    if user_id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    if isinstance(user_id, str):
        try:
            user_id = UUID(user_id)
        except ValueError as exc:  # pragma: no cover - defensive programming
            raise HTTPException(status_code=400, detail="Invalid user identifier") from exc

    membership_id: Optional[Any] = getattr(user, "logged_in_user_org", None)
    if membership_id is None and isinstance(user, dict):
        membership_id = user.get("logged_in_user_org")
        if membership_id is None:
            membership_id = user.get("user_org")

    if membership_id is None:
        raise HTTPException(status_code=404, detail="User is not logged into an organization")

    if isinstance(membership_id, str):
        try:
            membership_id = int(membership_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid organization membership identifier",
            ) from exc

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    if membership.user_id != user_id:
        raise HTTPException(status_code=403, detail="User does not belong to this organization")

    if base_match.organization_id != membership.organization_id:
        raise HTTPException(
            status_code=403,
            detail="Match data does not belong to the active organization",
        )

    event = await get_event_or_404(session, base_match.event_key)
    if event.year != expected_year:
        raise HTTPException(
            status_code=400,
            detail="Match data event does not match the expected season year",
        )

    season = await session.get(Season, base_match.season)
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found for provided match data")

    if season.year != expected_year:
        raise HTTPException(
            status_code=400,
            detail="Match data season does not match the expected season year",
        )

    match_user_id = getattr(base_match, "user_id", None)
    if match_user_id and match_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Match data user does not match the authenticated user",
        )

    payload: Dict[str, Any] = {
        **match_payload,
        "user_id": user_id,
        "organization_id": membership.organization_id,
    }
    payload["notes"] = payload.get("notes") or ""
    payload.pop("timestamp", None)

    try:
        typed_match = cast(MatchDataType, _model_validate(match_model, payload))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid match data for this season") from exc

    statement = select(match_model).where(
        match_model.event_key == getattr(typed_match, "event_key"),
        match_model.match_number == getattr(typed_match, "match_number"),
        match_model.match_level == getattr(typed_match, "match_level"),
        match_model.team_number == getattr(typed_match, "team_number"),
        match_model.user_id == getattr(typed_match, "user_id"),
        match_model.organization_id == getattr(typed_match, "organization_id"),
    )
    result = await session.execute(statement)
    existing_match = result.scalars().first()

    if existing_match is None:
        raise HTTPException(
            status_code=404,
            detail="Match data has not been submitted for this match",
        )

    for field_name in _get_model_field_names(match_model):
        setattr(existing_match, field_name, getattr(typed_match, field_name))

    session.add(existing_match)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Match data conflicts with an existing submission for this match",
        ) from exc

    await session.refresh(existing_match)
    return cast(MatchDataType, existing_match)

async def edit_2025_match(session: AsyncSession, match: MatchData2025, user: User) -> MatchData2025:
    return await _edit_match_for_year(session, match, user, expected_year=2025, match_model=MatchData2025)

async def update_2025_match(session: AsyncSession, match: MatchData2025, user: User) -> None:
    await edit_2025_match(session, match, user)

async def submit_2026_match(session: AsyncSession, match: MatchData2026, user: User) -> MatchData:
    return await _submit_match_for_year(
        session,
        match,
        user,
        expected_year=2026,
        match_model=MatchData2026,
    )

async def edit_2026_match(session: AsyncSession, match: MatchData2026, user: User) -> MatchData2026:
    return await _edit_match_for_year(session, match, user, expected_year=2026, match_model=MatchData2026)

async def update_2026_match(session: AsyncSession, match: MatchData2026, user: User) -> None:
    await edit_2026_match(session, match, user)
