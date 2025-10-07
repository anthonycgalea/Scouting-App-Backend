import os
from enum import Enum
from datetime import datetime
from math import sqrt
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlmodel import Field, SQLModel, delete, select
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
    OrganizationEventAlliance,
    OrgEventAllianceInviteStatus,
    UserOrganization,
    UserRole,
    EventRankings,
    StatboticsData,
)
from services.scoring import (
    calculate_endgame_points,
    extract_field_value,
    resolve_endgame_points_mapping,
    resolve_weight_mapping,
)
from services.season import get_season_by_year_or_404


async def get_scouting_alliance_organization_ids(
    session: AsyncSession, event_key: str, organization_id: int | None
) -> Set[int]:
    """Return organization identifiers accessible through scouting alliances.

    The result always includes ``organization_id`` when provided and adds any
    organizations that have accepted scouting alliances for the specified
    ``event_key``. Alliances are considered in both directions so that an
    organization gains access when it invited another organization or accepted
    an invitation from someone else.
    """

    if organization_id is None:
        return set()

    accessible_ids: Set[int] = {int(organization_id)}

    org_event_statement = select(OrganizationEvent.id).where(
        OrganizationEvent.event_key == event_key,
        OrganizationEvent.organization_id == organization_id,
    )
    org_event_result = await session.execute(org_event_statement)
    org_event_id = org_event_result.scalar_one_or_none()

    if org_event_id is not None:
        outgoing_statement = select(OrganizationEventAlliance.other_organization_id).where(
            OrganizationEventAlliance.orgevent_Uid == org_event_id,
            OrganizationEventAlliance.org_invite_status
            == OrgEventAllianceInviteStatus.ACCEPTED,
        )
        outgoing_result = await session.execute(outgoing_statement)
        accessible_ids.update(
            org_id for org_id in outgoing_result.scalars().all() if org_id is not None
        )

    incoming_statement = (
        select(OrganizationEvent.organization_id)
        .join(
            OrganizationEventAlliance,
            OrganizationEventAlliance.orgevent_Uid == OrganizationEvent.id,
        )
        .where(
            OrganizationEvent.event_key == event_key,
            OrganizationEventAlliance.other_organization_id == organization_id,
            OrganizationEventAlliance.org_invite_status
            == OrgEventAllianceInviteStatus.ACCEPTED,
        )
    )
    incoming_result = await session.execute(incoming_statement)
    accessible_ids.update(
        org_id for org_id in incoming_result.scalars().all() if org_id is not None
    )

    return accessible_ids

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
STATBOTICS_API_ENDPOINT = os.getenv("STATBOTICS_API_ENDPOINT", "https://api.statbotics.io/v3")

class TeamRecordResponse(SQLModel):
    team_number: int
    team_name: str
    location: str


class EventRankingResponse(SQLModel):
    event_key: str
    rank: int
    team_number: int
    team_name: Optional[str]
    ranking_points: int
    matches_played: int
    ranking_tiebreaker_1: float
    ranking_tiebreaker_2: float


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


class MetricStatistics(SQLModel):
    average: float = 0.0
    standard_deviation: float = 0.0


class PhaseMetrics(SQLModel):
    level4: MetricStatistics = Field(default_factory=MetricStatistics)
    level3: MetricStatistics = Field(default_factory=MetricStatistics)
    level2: MetricStatistics = Field(default_factory=MetricStatistics)
    level1: MetricStatistics = Field(default_factory=MetricStatistics)
    net: MetricStatistics = Field(default_factory=MetricStatistics)
    processor: MetricStatistics = Field(default_factory=MetricStatistics)
    total_points: MetricStatistics = Field(default_factory=MetricStatistics)


class TeamMatchPreview(SQLModel):
    team_number: int
    auto: PhaseMetrics
    teleop: PhaseMetrics
    endgame: MetricStatistics
    total_points: MetricStatistics


class LevelAverages(SQLModel):
    level4: float = 0.0
    level3: float = 0.0
    level2: float = 0.0
    level1: float = 0.0


class AllianceLevelAverages(SQLModel):
    auto: LevelAverages
    teleop: LevelAverages
    adjusted: LevelAverages


class AllianceMatchPreview(SQLModel):
    teams: List[TeamMatchPreview]
    alliance_level_averages: AllianceLevelAverages


class MatchPreviewResponse(SQLModel):
    season: int
    red: AllianceMatchPreview
    blue: AllianceMatchPreview


DEFAULT_AUTO_WEIGHTS: Dict[str, float] = {
    "al4c": 7.0,
    "al3c": 6.0,
    "al2c": 4.0,
    "al1c": 3.0,
    "aNet": 4.0,
    "aProcessor": 2.0,
}


DEFAULT_TELEOP_WEIGHTS: Dict[str, float] = {
    "tl4c": 5.0,
    "tl3c": 4.0,
    "tl2c": 3.0,
    "tl1c": 2.0,
    "tNet": 4.0,
    "tProcessor": 2.0,
}


DEFAULT_ENDGAME_POINTS: Dict[str, float] = {
    "NONE": 0.0,
    "PARK": 2.0,
    "SHALLOW": 6.0,
    "DEEP": 12.0,
}



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


PHASE_METRIC_KEYS: Tuple[str, ...] = (
    "level4",
    "level3",
    "level2",
    "level1",
    "net",
    "processor",
    "total_points",
)


LEVEL_KEYS: Tuple[str, ...] = (
    "level4",
    "level3",
    "level2",
    "level1",
)


AUTO_LEVEL_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("al4c", "level4"),
    ("al3c", "level3"),
    ("al2c", "level2"),
    ("al1c", "level1"),
)


TELEOP_LEVEL_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("tl4c", "level4"),
    ("tl3c", "level3"),
    ("tl2c", "level2"),
    ("tl1c", "level1"),
)


AUTO_ADDITIONAL_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("aNet", "net"),
    ("aProcessor", "processor"),
)


TELEOP_ADDITIONAL_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("tNet", "net"),
    ("tProcessor", "processor"),
)


MATCH_MODEL_AUTO_WEIGHTS_ATTR = "AUTO_POINT_WEIGHTS"
MATCH_MODEL_TELEOP_WEIGHTS_ATTR = "TELEOP_POINT_WEIGHTS"
MATCH_MODEL_ENDGAME_POINTS_ATTR = "ENDGAME_POINT_VALUES"


def _calculate_average(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _calculate_std_dev(values: Sequence[float], average: Optional[float] = None) -> float:
    if not values or len(values) <= 1:
        return 0.0

    if average is None:
        average = _calculate_average(values)

    variance = sum((value - average) ** 2 for value in values) / len(values)
    if variance <= 0:
        return 0.0
    return sqrt(variance)


def _calculate_metric_statistics(values: Sequence[float]) -> MetricStatistics:
    if not values:
        return MetricStatistics()

    average = _calculate_average(values)
    std_dev = _calculate_std_dev(values, average)
    return MetricStatistics(average=average, standard_deviation=std_dev)


def _initialize_phase_metric_lists() -> Dict[str, List[float]]:
    return {key: [] for key in PHASE_METRIC_KEYS}


def _initialize_count_lists(field_mapping: Tuple[Tuple[str, str], ...]) -> Dict[str, List[float]]:
    return {field: [] for field, _ in field_mapping}


def _phase_metrics_from_lists(metric_lists: Dict[str, List[float]]) -> PhaseMetrics:
    return PhaseMetrics(
        level4=_calculate_metric_statistics(metric_lists["level4"]),
        level3=_calculate_metric_statistics(metric_lists["level3"]),
        level2=_calculate_metric_statistics(metric_lists["level2"]),
        level1=_calculate_metric_statistics(metric_lists["level1"]),
        net=_calculate_metric_statistics(metric_lists["net"]),
        processor=_calculate_metric_statistics(metric_lists["processor"]),
        total_points=_calculate_metric_statistics(metric_lists["total_points"]),
    )


def _average_counts(
    count_lists: Dict[str, List[float]],
    field_mapping: Tuple[Tuple[str, str], ...],
) -> Dict[str, float]:
    return {
        alias: _calculate_average(count_lists.get(field, []))
        for field, alias in field_mapping
    }


def _build_team_preview_from_records(
    records: Sequence[SQLModel],
    team_number: int,
    auto_weights: Dict[str, float],
    teleop_weights: Dict[str, float],
    endgame_points: Dict[str, float],
) -> Tuple[TeamMatchPreview, Dict[str, Dict[str, float]]]:
    auto_metric_lists = _initialize_phase_metric_lists()
    teleop_metric_lists = _initialize_phase_metric_lists()
    auto_count_lists = _initialize_count_lists(AUTO_LEVEL_FIELDS)
    teleop_count_lists = _initialize_count_lists(TELEOP_LEVEL_FIELDS)
    endgame_values: List[float] = []
    total_match_points: List[float] = []

    for record in records:
        auto_total = 0.0
        teleop_total = 0.0

        for field, alias in AUTO_LEVEL_FIELDS:
            count = extract_field_value(record, field)
            auto_count_lists[field].append(count)
            auto_metric_lists[alias].append(count)
            points = count * auto_weights.get(field, 0.0)
            auto_total += points

        for field, alias in AUTO_ADDITIONAL_FIELDS:
            count = extract_field_value(record, field)
            auto_metric_lists[alias].append(count)
            auto_total += count * auto_weights.get(field, 0.0)

        auto_metric_lists["total_points"].append(auto_total)

        for field, alias in TELEOP_LEVEL_FIELDS:
            count = extract_field_value(record, field)
            teleop_count_lists[field].append(count)
            teleop_metric_lists[alias].append(count)
            points = count * teleop_weights.get(field, 0.0)
            teleop_total += points

        for field, alias in TELEOP_ADDITIONAL_FIELDS:
            count = extract_field_value(record, field)
            teleop_metric_lists[alias].append(count)
            teleop_total += count * teleop_weights.get(field, 0.0)

        teleop_metric_lists["total_points"].append(teleop_total)

        endgame_value = calculate_endgame_points(getattr(record, "endgame", None), endgame_points)
        endgame_values.append(endgame_value)
        total_match_points.append(auto_total + teleop_total + endgame_value)

    team_preview = TeamMatchPreview(
        team_number=team_number,
        auto=_phase_metrics_from_lists(auto_metric_lists),
        teleop=_phase_metrics_from_lists(teleop_metric_lists),
        endgame=_calculate_metric_statistics(endgame_values),
        total_points=_calculate_metric_statistics(total_match_points),
    )

    counts_average = {
        "auto": _average_counts(auto_count_lists, AUTO_LEVEL_FIELDS),
        "teleop": _average_counts(teleop_count_lists, TELEOP_LEVEL_FIELDS),
    }

    return team_preview, counts_average


def _apply_level_capacity(
    auto_levels: Dict[str, float],
    teleop_levels: Dict[str, float],
) -> Dict[str, float]:
    level_order = list(LEVEL_KEYS)
    capacity = {"level4": 12.0, "level3": 12.0, "level2": 12.0, "level1": float("inf")}

    auto_remaining = {level: float(auto_levels.get(level, 0.0)) for level in level_order}
    teleop_remaining = {level: float(teleop_levels.get(level, 0.0)) for level in level_order}
    placed_auto = {level: 0.0 for level in level_order}
    placed_teleop = {level: 0.0 for level in level_order}

    for index, level in enumerate(level_order):
        level_capacity = capacity[level]

        auto_to_place = min(auto_remaining[level], level_capacity)
        placed_auto[level] += auto_to_place
        level_capacity -= auto_to_place
        leftover_auto = auto_remaining[level] - auto_to_place

        teleop_to_place = min(teleop_remaining[level], level_capacity)
        placed_teleop[level] += teleop_to_place
        level_capacity -= teleop_to_place
        leftover_teleop = teleop_remaining[level] - teleop_to_place

        if index + 1 < len(level_order):
            next_level = level_order[index + 1]
            auto_remaining[next_level] += leftover_auto
            teleop_remaining[next_level] += leftover_teleop
        else:
            placed_auto[level] += leftover_auto
            placed_teleop[level] += leftover_teleop

    return {
        level: placed_auto[level] + placed_teleop[level]
        for level in level_order
    }


def _calculate_alliance_level_averages(
    team_level_counts: Iterable[Dict[str, Dict[str, float]]],
) -> AllianceLevelAverages:
    auto_totals = {level: 0.0 for level in LEVEL_KEYS}
    teleop_totals = {level: 0.0 for level in LEVEL_KEYS}

    for counts in team_level_counts:
        auto_counts = counts.get("auto", {})
        teleop_counts = counts.get("teleop", {})
        for level in LEVEL_KEYS:
            auto_totals[level] += float(auto_counts.get(level, 0.0))
            teleop_totals[level] += float(teleop_counts.get(level, 0.0))

    adjusted_totals = _apply_level_capacity(auto_totals, teleop_totals)

    return AllianceLevelAverages(
        auto=LevelAverages(**auto_totals),
        teleop=LevelAverages(**teleop_totals),
        adjusted=LevelAverages(**adjusted_totals),
    )


async def _fetch_team_records(
    session: AsyncSession,
    match_model: type[SQLModel],
    event_key: str,
    organization_id: int,
    team_number: int,
) -> List[SQLModel]:
    statement = select(match_model).where(
        match_model.event_key == event_key,
        match_model.organization_id == organization_id,
        match_model.team_number == team_number,
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def _build_alliance_preview(
    session: AsyncSession,
    match_model: type[SQLModel],
    event_key: str,
    organization_id: int,
    team_numbers: Sequence[int],
    auto_weights: Dict[str, float],
    teleop_weights: Dict[str, float],
    endgame_points: Dict[str, float],
) -> AllianceMatchPreview:
    teams: List[TeamMatchPreview] = []
    level_counts: List[Dict[str, Dict[str, float]]] = []

    for team_number in team_numbers:
        records = await _fetch_team_records(
            session,
            match_model,
            event_key,
            organization_id,
            int(team_number),
        )
        team_preview, counts_average = _build_team_preview_from_records(
            records,
            int(team_number),
            auto_weights,
            teleop_weights,
            endgame_points,
        )
        teams.append(team_preview)
        level_counts.append(counts_average)

    alliance_level_averages = _calculate_alliance_level_averages(level_counts)
    return AllianceMatchPreview(teams=teams, alliance_level_averages=alliance_level_averages)


async def get_match_preview(
    session: AsyncSession,
    user: dict,
    match_number: int,
    match_level: str,
) -> MatchPreviewResponse:
    event_key = await get_active_event_key_for_user(session, user)
    event = await get_event_or_404(session, event_key)
    membership = await get_user_membership_or_404(session, user)

    match = await get_match_or_404(session, event_key, match_number, match_level)
    season = await get_season_by_year_or_404(session, event.year)

    match_model = MATCH_DATA_MODELS_BY_YEAR.get(event.year)
    if match_model is None:
        raise HTTPException(
            status_code=404,
            detail="Match data is not available for this event",
        )

    auto_weights = resolve_weight_mapping(match_model, MATCH_MODEL_AUTO_WEIGHTS_ATTR, DEFAULT_AUTO_WEIGHTS)
    teleop_weights = resolve_weight_mapping(match_model, MATCH_MODEL_TELEOP_WEIGHTS_ATTR, DEFAULT_TELEOP_WEIGHTS)
    endgame_points = resolve_endgame_points_mapping(match_model, MATCH_MODEL_ENDGAME_POINTS_ATTR, DEFAULT_ENDGAME_POINTS)

    red_teams = [match.red1_id, match.red2_id, match.red3_id]
    blue_teams = [match.blue1_id, match.blue2_id, match.blue3_id]

    red_preview = await _build_alliance_preview(
        session,
        match_model,
        event_key,
        membership.organization_id,
        red_teams,
        auto_weights,
        teleop_weights,
        endgame_points,
    )

    blue_preview = await _build_alliance_preview(
        session,
        match_model,
        event_key,
        membership.organization_id,
        blue_teams,
        auto_weights,
        teleop_weights,
        endgame_points,
    )

    return MatchPreviewResponse(
        season=season.id,
        red=red_preview,
        blue=blue_preview,
    )


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

async def get_event_rankings_or_404(
    session: AsyncSession, eventCode: str
) -> List[EventRankingResponse]:
    statement = (
        select(EventRankings, TeamRecord.team_name)
        .join(TeamRecord, TeamRecord.team_number == EventRankings.team_number, isouter=True)
        .where(EventRankings.event_key == eventCode)
        .order_by(EventRankings.rank)
    )
    result = await session.execute(statement)
    rankings = result.all()
    if not rankings:
        raise HTTPException(status_code=404, detail="No rankings found for this event")
    return [
        EventRankingResponse(
            event_key=ranking.event_key,
            rank=ranking.rank,
            team_number=ranking.team_number,
            team_name=team_name,
            ranking_points=ranking.ranking_points,
            matches_played=ranking.matches_played,
            ranking_tiebreaker_1=ranking.ranking_tiebreaker_1,
            ranking_tiebreaker_2=ranking.ranking_tiebreaker_2,
        )
        for ranking, team_name in rankings
    ]

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


async def get_user_membership_or_404(
    session: AsyncSession,
    user: dict,
) -> UserOrganization:
    """Return the organization membership for the authenticated user."""

    return await _get_user_membership(session, user)


async def require_lead_or_admin_membership(
    session: AsyncSession,
    user: dict,
) -> UserOrganization:
    """Ensure the current user is an organization lead or admin."""

    return await _require_lead_or_admin_membership(session, user)


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


async def update_statbotics_data_for_event(
    session: AsyncSession,
    eventCode: str,
) -> List[StatboticsData]:
    await get_event_or_404(session, eventCode)

    url = f"{STATBOTICS_API_ENDPOINT}/team_events?event={eventCode}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="Failed to retrieve Statbotics data",
        )

    payload = response.json()
    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="Invalid Statbotics payload")

    await session.execute(
        delete(StatboticsData).where(StatboticsData.event_key == eventCode)
    )

    records: List[StatboticsData] = []

    for entry in payload:
        team_number = entry.get("team")
        if team_number is None:
            continue

        epa = entry.get("epa") or {}
        breakdown = epa.get("breakdown")
        if not isinstance(breakdown, dict):
            breakdown = {}

        statbotics_record = StatboticsData(
            event_key=eventCode,
            team_number=int(team_number),
            total_points=_coerce_float(breakdown.get("total_points")),
            auto_points=_coerce_float(breakdown.get("auto_points")),
            teleop_points=_coerce_float(breakdown.get("teleop_points")),
            endgame_points=_coerce_float(breakdown.get("endgame_points")),
        )

        session.add(statbotics_record)
        records.append(statbotics_record)

    await session.commit()

    return records
