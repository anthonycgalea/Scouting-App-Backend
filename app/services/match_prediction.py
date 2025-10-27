"""Services for working with match prediction data."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import sqrt
from numbers import Number
from typing import Any, DefaultDict, Dict, List, Sequence, Set, Tuple, TypeVar

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    MatchData,
    MatchPredictions2025,
    Organization,
    OrganizationEvent,
    Prescout2025,
    Season,
    StatboticsData,
    UserOrganization,
)
from app.services.event import (
    DEFAULT_AUTO_WEIGHTS,
    DEFAULT_ENDGAME_POINTS,
    DEFAULT_TELEOP_WEIGHTS,
    MATCH_DATA_MODELS_BY_YEAR,
    MATCH_MODEL_AUTO_WEIGHTS_ATTR,
    MATCH_MODEL_ENDGAME_POINTS_ATTR,
    MATCH_MODEL_TELEOP_WEIGHTS_ATTR,
    get_active_event_key_for_user,
    get_event_or_404,
    get_match_or_404,
    get_scouting_alliance_organization_ids,
    update_statbotics_data_for_event,
)
from app.services.scoring import (
    calculate_endgame_points,
    calculate_phase_points,
    resolve_endgame_points_mapping,
    resolve_weight_mapping,
)

RecordType = TypeVar("RecordType", bound=MatchData)

PRESCOUT_MODELS_BY_YEAR = {
    2025: Prescout2025,
}

WEIGHT_SCHEDULE = [3, 3, 3, 3, 3, 2, 2, 2, 1, 1]
MATCH_DATA_FIELDS_TO_EXCLUDE = {
    "season",
    "team_number",
    "event_key",
    "match_number",
    "match_level",
    "user_id",
    "organization_id",
    "timestamp",
    "notes",
}

MATCH_PREDICTION_MODELS_BY_YEAR = {
    2025: MatchPredictions2025,
}

RP_PREDICTION_FIELDS: Tuple[str, ...] = (
    "red_auto_rp",
    "blue_auto_rp",
    "red_endgame_rp",
    "blue_endgame_rp",
    "red_w_coral_rp",
    "blue_w_coral_rp",
    "red_r_coral_rp",
    "blue_r_coral_rp",
    "red_rw_win_pct",
    "blue_rw_win_pct",
    "red_wr_win_pct",
    "blue_wr_win_pct",
    "red_rr_win_pct",
    "blue_rr_win_pct",
)


async def _get_season_for_year(session: AsyncSession, year: int) -> Season:
    statement = select(Season).where(Season.year == year)
    result = await session.execute(statement)
    season = result.scalar_one_or_none()
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found for event year")
    return season


async def _get_organization_ids_for_event(
    session: AsyncSession, match_model: type[MatchData], event_key: str
) -> List[int]:
    statement = (
        select(match_model.organization_id)
        .where(match_model.event_key == event_key)
        .distinct()
    )
    result = await session.execute(statement)
    organization_ids = [org_id for org_id in result.scalars().all() if org_id is not None]

    if organization_ids:
        return organization_ids

    org_event_stmt = select(OrganizationEvent.organization_id).where(
        OrganizationEvent.event_key == event_key
    )
    org_event_result = await session.execute(org_event_stmt)
    return list({org_id for org_id in org_event_result.scalars().all() if org_id is not None})


async def _collect_team_records(
    session: AsyncSession,
    match_model: type[MatchData],
    event_key: str,
    team_number: int,
    organization_ids: Sequence[int],
) -> List[MatchData]:
    if not organization_ids:
        return []

    statement = (
        select(match_model)
        .where(
            match_model.event_key == event_key,
            match_model.team_number == team_number,
            match_model.organization_id.in_(list(organization_ids)),
        )
        .order_by(match_model.match_number.desc())
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


def _sum_record_fields(record: MatchData, fields: Sequence[str]) -> float:
    total = 0.0
    for field in fields:
        value = getattr(record, field, 0)
        if value is None:
            continue
        try:
            total += float(value)
        except (TypeError, ValueError):
            continue
    return total


def _compute_weighted_metric(
    records: Sequence[MatchData], extractor: Any
) -> Tuple[float, float]:
    limited_records = list(records[: len(WEIGHT_SCHEDULE)])
    weights = list(WEIGHT_SCHEDULE[: len(limited_records)])

    weighted_values: List[Tuple[float, float]] = []
    for record, weight in zip(limited_records, weights):
        try:
            value = extractor(record)
        except Exception:  # pragma: no cover - defensive programming
            value = None
        if value is None:
            continue
        try:
            weighted_values.append((float(value), float(weight)))
        except (TypeError, ValueError):
            continue

    if not weighted_values:
        return 0.0, 0.0

    total_weight = sum(weight for _, weight in weighted_values)
    if total_weight == 0:
        return 0.0, 0.0

    weighted_sum = sum(value * weight for value, weight in weighted_values)
    mean = weighted_sum / total_weight

    variance = sum(weight * (value - mean) ** 2 for value, weight in weighted_values)
    variance /= total_weight

    return mean, sqrt(variance)


def _compute_weighted_statistics(
    records: Sequence[MatchData],
    statbotics_value: float | None,
) -> Tuple[float, float]:
    limited_records = list(records[: len(WEIGHT_SCHEDULE)])
    weights = list(WEIGHT_SCHEDULE[: len(limited_records)])

    weighted_values: List[Tuple[float, float]] = []
    for record, weight in zip(limited_records, weights):
        total_points = getattr(record, "total_points", None)
        if total_points is None:
            continue
        weighted_values.append((float(total_points), float(weight)))

    if statbotics_value is not None and len(weighted_values) < len(WEIGHT_SCHEDULE):
        for weight in WEIGHT_SCHEDULE[len(weighted_values) :]:
            weighted_values.append((float(statbotics_value), float(weight)))

    if not weighted_values:
        return 0.0, 0.0

    total_weight = sum(weight for _, weight in weighted_values)
    if total_weight == 0:
        return 0.0, 0.0

    weighted_sum = sum(value * weight for value, weight in weighted_values)
    mean = weighted_sum / total_weight

    variance = sum(weight * (value - mean) ** 2 for value, weight in weighted_values)
    variance /= total_weight

    return mean, sqrt(variance)


async def _get_team_statistics(
    session: AsyncSession,
    match_model: type[MatchData],
    event_key: str,
    team_number: int,
    organization_ids: Sequence[int],
    auto_weights: Dict[str, float],
    teleop_weights: Dict[str, float],
    endgame_points: Dict[str, float],
) -> Dict[str, Tuple[float, float]]:
    records = await _collect_team_records(
        session, match_model, event_key, team_number, organization_ids
    )
    if records:
        _apply_calculated_fields(records, auto_weights, teleop_weights, endgame_points)

    statbotics_record = await session.get(StatboticsData, (event_key, int(team_number)))
    statbotics_total = None
    if statbotics_record is not None:
        statbotics_total = float(statbotics_record.total_points)

    total_mean, total_std = _compute_weighted_statistics(records, statbotics_total)

    def _extract_climb_probability(record: MatchData) -> float | None:
        raw_probability = getattr(record, "climb_rate", None)
        if raw_probability is None:
            raw_probability = getattr(record, "climb_success", None)

        if raw_probability is None:
            endgame_value = getattr(record, "endgame", None)
            if endgame_value is not None:
                normalized = str(getattr(endgame_value, "value", endgame_value)).upper()
                raw_probability = 1.0 if normalized == "DEEP" else 0.0

        if raw_probability is None:
            endgame_points_value = getattr(record, "endgame_points", None)
            if endgame_points_value is not None:
                try:
                    raw_probability = 1.0 if float(endgame_points_value) >= 12.0 else 0.0
                except (TypeError, ValueError):
                    return None

        if raw_probability is None:
            return None

        try:
            probability = float(raw_probability)
        except (TypeError, ValueError):
            return None

        if probability < 0.0:
            return 0.0
        if probability > 1.0:
            return 1.0
        return probability

    auto_coral_mean, auto_coral_std = _compute_weighted_metric(
        records, lambda record: _sum_record_fields(record, ("al4c", "al3c", "al2c", "al1c"))
    )
    total_coral_mean, total_coral_std = _compute_weighted_metric(
        records,
        lambda record: _sum_record_fields(
            record,
            (
                "al4c",
                "al3c",
                "al2c",
                "al1c",
                "tl4c",
                "tl3c",
                "tl2c",
                "tl1c",
            ),
        ),
    )

    processor_mean, processor_std = _compute_weighted_metric(
        records, lambda record: _sum_record_fields(record, ("aProcessor", "tProcessor"))
    )
    endgame_mean, endgame_std = _compute_weighted_metric(
        records, lambda record: getattr(record, "endgame_points", 0.0)
    )

    climb_rate_mean, climb_rate_std = _compute_weighted_metric(
        records, _extract_climb_probability
    )

    base_total_mean = total_mean - (climb_rate_mean * 12.0)
    climb_variance = 144.0 * climb_rate_mean * (1.0 - climb_rate_mean)
    base_total_variance = max(0.0, total_std**2 - climb_variance)
    base_total_std = sqrt(base_total_variance)

    return {
        "total": (total_mean, total_std),
        "total_without_climb": (base_total_mean, base_total_std),
        "auto_coral": (auto_coral_mean, auto_coral_std),
        "total_coral": (total_coral_mean, total_coral_std),
        "processor": (processor_mean, processor_std),
        "endgame": (endgame_mean, endgame_std),
        "climb_rate": (climb_rate_mean, climb_rate_std),
    }

def _apply_calculated_fields(
    records: Sequence[MatchData],
    auto_weights: Dict[str, float],
    teleop_weights: Dict[str, float],
    endgame_points: Dict[str, float],
) -> None:
    if not records:
        return

    for record in records:
        if getattr(record, "__pydantic_extra__", None) is None:
            # Ensure Pydantic models fetched from the database have a mutable
            # ``__pydantic_extra__`` container before assigning dynamic
            # attributes.  With Pydantic v2 SQLModel instances may initialise
            # ``__pydantic_extra__`` as ``None`` when ``extra='allow'`` is set
            # on the base model, which would otherwise raise a ``TypeError``
            # when we try to attach calculated fields.
            object.__setattr__(record, "__pydantic_extra__", {})

        autonomous_points = calculate_phase_points(record, auto_weights)
        teleop_points = calculate_phase_points(record, teleop_weights)
        endgame_points_total = calculate_endgame_points(
            getattr(record, "endgame", None), endgame_points
        )

        record.autonomous_points = autonomous_points
        record.teleop_points = teleop_points
        record.endgame_points = endgame_points_total
        climb_points = 12.0 if endgame_points_total >= 12.0 else 0.0
        record.climb_points = climb_points
        record.climb_success = 1.0 if climb_points >= 12.0 else 0.0
        record.total_points = (
            autonomous_points + teleop_points + endgame_points_total
        )
        record.total_points_without_climb = record.total_points - climb_points


def _normalize_user_payload(user: Any) -> Dict[str, Any]:
    if isinstance(user, dict):
        return user

    return {
        "id": getattr(user, "id", None),
        "user_org": getattr(user, "logged_in_user_org", None),
    }


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


def _collect_latest_matches(
    records: Sequence[RecordType],
    seen_matches: Set[Tuple[str, int]],
    limit: int,
    preferred_organization_id: int | None = None,
) -> List[RecordType]:
    collected: List[RecordType] = []
    unique_matches = len(seen_matches)
    collected_index: Dict[Tuple[str, int], int] = {}

    for record in records:
        match_identifier = (record.match_level, record.match_number)
        if match_identifier in seen_matches:
            if preferred_organization_id is None:
                continue

            existing_index = collected_index.get(match_identifier)
            if existing_index is None:
                continue

            preferred_existing = (
                getattr(collected[existing_index], "organization_id", None)
                == preferred_organization_id
            )
            is_preferred = getattr(record, "organization_id", None) == preferred_organization_id

            if is_preferred and not preferred_existing:
                collected[existing_index] = record
            continue

        if unique_matches >= limit:
            break

        seen_matches.add(match_identifier)
        unique_matches += 1
        collected_index[match_identifier] = len(collected)
        collected.append(record)

    return collected


async def _fetch_match_records(
    session: AsyncSession,
    model: type[RecordType],
    event_key: str,
    organization_ids: Sequence[int],
) -> List[RecordType]:
    if not organization_ids:
        return []

    statement = (
        select(model)
        .where(
            model.event_key == event_key,
            model.organization_id.in_(list(organization_ids)),
        )
        .order_by(model.match_number.desc())
    )

    result = await session.execute(statement)
    return list(result.scalars().all())


async def retrieve_prediction_data(session: AsyncSession, user: Any) -> List[MatchData]:
    """Return up to ten recent matches for the active event.

    The service prioritises matches that have been fully scouted. When fewer than
    ten matches are available, prescout data for the event is used to supplement
    the response. The function never raises an error when the available match
    data totals fewer than ten matches.
    """

    user_payload = _normalize_user_payload(user)

    event_key = await get_active_event_key_for_user(session, user_payload)
    event = await get_event_or_404(session, event_key)
    membership = await _get_user_membership_or_404(session, user_payload)

    match_model = MATCH_DATA_MODELS_BY_YEAR.get(event.year)
    prescout_model = PRESCOUT_MODELS_BY_YEAR.get(event.year)

    alliance_organization_ids = list(
        await get_scouting_alliance_organization_ids(
            session, event_key, membership.organization_id
        )
    )

    seen_matches: Set[Tuple[str, int]] = set()
    ordered_records: List[MatchData] = []
    limit = 10

    if match_model is not None:
        auto_weights = resolve_weight_mapping(
            match_model, MATCH_MODEL_AUTO_WEIGHTS_ATTR, DEFAULT_AUTO_WEIGHTS
        )
        teleop_weights = resolve_weight_mapping(
            match_model, MATCH_MODEL_TELEOP_WEIGHTS_ATTR, DEFAULT_TELEOP_WEIGHTS
        )
        endgame_points = resolve_endgame_points_mapping(
            match_model, MATCH_MODEL_ENDGAME_POINTS_ATTR, DEFAULT_ENDGAME_POINTS
        )

        scouted_records = await _fetch_match_records(
            session, match_model, event_key, alliance_organization_ids
        )
        latest_matches = _collect_latest_matches(
            scouted_records,
            seen_matches,
            limit,
            preferred_organization_id=membership.organization_id,
        )
        _apply_calculated_fields(
            latest_matches, auto_weights, teleop_weights, endgame_points
        )
        ordered_records.extend(latest_matches)

    if len(seen_matches) < limit and prescout_model is not None:
        prescout_auto_weights = resolve_weight_mapping(
            prescout_model, MATCH_MODEL_AUTO_WEIGHTS_ATTR, DEFAULT_AUTO_WEIGHTS
        )
        prescout_teleop_weights = resolve_weight_mapping(
            prescout_model, MATCH_MODEL_TELEOP_WEIGHTS_ATTR, DEFAULT_TELEOP_WEIGHTS
        )
        prescout_endgame_points = resolve_endgame_points_mapping(
            prescout_model, MATCH_MODEL_ENDGAME_POINTS_ATTR, DEFAULT_ENDGAME_POINTS
        )

        prescout_records = await _fetch_match_records(
            session, prescout_model, event_key, alliance_organization_ids
        )
        latest_prescout = _collect_latest_matches(
            prescout_records,
            seen_matches,
            limit,
            preferred_organization_id=membership.organization_id,
        )
        _apply_calculated_fields(
            latest_prescout,
            prescout_auto_weights,
            prescout_teleop_weights,
            prescout_endgame_points,
        )
        ordered_records.extend(latest_prescout)

    return ordered_records


async def calculate_weighted_match_statistics(
    session: AsyncSession, user: Any
) -> Dict[str, Any]:
    """Return weighted averages and standard deviations for recent match data.

    The calculation uses :func:`retrieve_prediction_data` to gather up to the ten
    most recent matches and applies the following weight schedule based on
    recency: the five most recent matches are weighted ``3``, matches six
    through eight are weighted ``2`` and matches nine and ten are weighted ``1``.
    """

    matches = await retrieve_prediction_data(session, user)

    if not matches:
        statbotics_weights: List[float] = list(WEIGHT_SCHEDULE)
    else:
        statbotics_weights = list(WEIGHT_SCHEDULE[len(matches) :])

    statbotics_record: StatboticsData | None = None
    if statbotics_weights:
        user_payload = _normalize_user_payload(user)
        event_key = await get_active_event_key_for_user(session, user_payload)
        membership = await _get_user_membership_or_404(session, user_payload)

        team_number: int | None = None
        organization = await session.get(Organization, membership.organization_id)
        if organization is not None and organization.team_number is not None:
            team_number = organization.team_number

        if team_number is None:
            for match in matches:
                match_team = getattr(match, "team_number", None)
                if match_team is not None:
                    team_number = int(match_team)
                    break

        if team_number is not None:
            statbotics_record = await session.get(
                StatboticsData, (event_key, int(team_number))
            )

            if statbotics_record is None and statbotics_weights:
                try:
                    await update_statbotics_data_for_event(session, event_key)
                except HTTPException:
                    pass

                statbotics_record = await session.get(
                    StatboticsData, (event_key, int(team_number))
                )

    if not matches and statbotics_record is None:
        return {"sample_size": 0, "statistics": {}}

    weighted_values: DefaultDict[str, List[Tuple[float, float]]] = defaultdict(list)

    weights = list(WEIGHT_SCHEDULE[: len(matches)])
    if len(weights) < len(matches):
        weights.extend([WEIGHT_SCHEDULE[-1]] * (len(matches) - len(weights)))

    for match, weight in zip(matches, weights):

        match_data = match.model_dump()
        for field, value in match_data.items():
            if field in MATCH_DATA_FIELDS_TO_EXCLUDE:
                continue

            if isinstance(value, Number):
                weighted_values[field].append((float(value), float(weight)))

    if statbotics_record is not None and statbotics_weights:
        supplemental_fields = {
            "autonomous_points": statbotics_record.auto_points,
            "teleop_points": statbotics_record.teleop_points,
            "endgame_points": statbotics_record.endgame_points,
            "total_points": statbotics_record.total_points,
        }
        for weight in statbotics_weights:
            for field, value in supplemental_fields.items():
                weighted_values[field].append((float(value), float(weight)))

    statistics: Dict[str, Dict[str, float]] = {}

    for field, values in weighted_values.items():
        total_weight = sum(weight for _, weight in values)
        if total_weight == 0:
            continue

        weighted_sum = sum(value * weight for value, weight in values)
        mean = weighted_sum / total_weight

        variance = sum(weight * (value - mean) ** 2 for value, weight in values)
        variance /= total_weight

        statistics[field] = {
            "weighted_average": mean,
            "weighted_standard_deviation": sqrt(variance),
        }

    return {"sample_size": len(matches), "statistics": statistics}


async def get_match_prediction_for_user_organization(
    session: AsyncSession,
    user: Any,
    match_level: str,
    match_number: int,
):
    """Return the stored match prediction for the user's organization.

    The lookup uses the active event configured for the organization the user is
    logged into. A ``404`` is raised when predictions are unavailable for the
    event year or when no prediction has been generated for the requested match.
    """

    user_payload = _normalize_user_payload(user)

    event_key = await get_active_event_key_for_user(session, user_payload)
    event = await get_event_or_404(session, event_key)
    membership = await _get_user_membership_or_404(session, user_payload)

    prediction_model = MATCH_PREDICTION_MODELS_BY_YEAR.get(event.year)
    if prediction_model is None:
        raise HTTPException(
            status_code=404,
            detail="Match predictions are not available for this event year",
        )

    alliance_organization_ids = list(
        await get_scouting_alliance_organization_ids(
            session, event_key, membership.organization_id
        )
    )

    if not alliance_organization_ids:
        raise HTTPException(status_code=404, detail="Match prediction not found")

    statement = select(prediction_model).where(
        prediction_model.event_key == event_key,
        prediction_model.match_number == int(match_number),
        prediction_model.match_level == match_level,
        prediction_model.organization_id.in_(alliance_organization_ids),
    )
    result = await session.execute(statement)
    predictions = result.scalars().all()

    if not predictions:
        raise HTTPException(status_code=404, detail="Match prediction not found")

    for prediction in predictions:
        if prediction.organization_id == membership.organization_id:
            return prediction

    return predictions[0]


async def list_match_predictions_for_event(
    session: AsyncSession,
    user: Any,
):
    """Return all stored match predictions for the active event."""

    user_payload = _normalize_user_payload(user)

    event_key = await get_active_event_key_for_user(session, user_payload)
    event = await get_event_or_404(session, event_key)
    membership = await _get_user_membership_or_404(session, user_payload)

    prediction_model = MATCH_PREDICTION_MODELS_BY_YEAR.get(event.year)
    if prediction_model is None:
        raise HTTPException(
            status_code=404,
            detail="Match predictions are not available for this event year",
        )

    statement = (
        select(prediction_model)
        .where(
            prediction_model.event_key == event_key,
            prediction_model.organization_id == membership.organization_id,
        )
        .order_by(
            prediction_model.match_level,
            prediction_model.match_number,
        )
    )

    result = await session.execute(statement)
    return list(result.scalars().all())


async def simulate_match_prediction(
    session: AsyncSession,
    event_code: str,
    match_level: str,
    match_number: int,
) -> Dict[int, Dict[str, float]]:
    """Run Monte Carlo simulations for a scheduled match and persist results."""

    event = await get_event_or_404(session, event_code)

    match_model = MATCH_DATA_MODELS_BY_YEAR.get(event.year)
    prediction_model = MATCH_PREDICTION_MODELS_BY_YEAR.get(event.year)
    if match_model is None or prediction_model is None:
        raise HTTPException(status_code=404, detail="Match predictions are not available for this event year")

    match_schedule = await get_match_or_404(session, event_code, match_number, match_level)
    season = await _get_season_for_year(session, event.year)

    auto_weights = resolve_weight_mapping(
        match_model, MATCH_MODEL_AUTO_WEIGHTS_ATTR, DEFAULT_AUTO_WEIGHTS
    )
    teleop_weights = resolve_weight_mapping(
        match_model, MATCH_MODEL_TELEOP_WEIGHTS_ATTR, DEFAULT_TELEOP_WEIGHTS
    )
    endgame_points = resolve_endgame_points_mapping(
        match_model, MATCH_MODEL_ENDGAME_POINTS_ATTR, DEFAULT_ENDGAME_POINTS
    )

    red_teams = [match_schedule.red1_id, match_schedule.red2_id, match_schedule.red3_id]
    blue_teams = [match_schedule.blue1_id, match_schedule.blue2_id, match_schedule.blue3_id]

    organization_ids = await _get_organization_ids_for_event(session, match_model, event_code)
    if not organization_ids:
        raise HTTPException(status_code=404, detail="No organizations found for match predictions")

    rng = np.random.default_rng()
    n_samples = 10_000
    now = datetime.now()
    results: Dict[int, Dict[str, float]] = {}
    processed_organization_ids: Set[int] = set()

    for organization_id in organization_ids:
        if organization_id is None:
            continue

        base_organization_id = int(organization_id)
        if base_organization_id in processed_organization_ids:
            continue

        alliance_organization_ids = list(
            await get_scouting_alliance_organization_ids(
                session, event_code, base_organization_id
            )
        )
        if not alliance_organization_ids:
            continue

        alliance_organization_ids = [
            int(org_id) for org_id in alliance_organization_ids if org_id is not None
        ]
        if not alliance_organization_ids:
            continue

        red_stats = [
            await _get_team_statistics(
                session,
                match_model,
                event_code,
                int(team_number),
                alliance_organization_ids,
                auto_weights,
                teleop_weights,
                endgame_points,
            )
            for team_number in red_teams
        ]
        blue_stats = [
            await _get_team_statistics(
                session,
                match_model,
                event_code,
                int(team_number),
                alliance_organization_ids,
                auto_weights,
                teleop_weights,
                endgame_points,
            )
            for team_number in blue_teams
        ]

        def _generate_alliance_samples(
            team_statistics: Sequence[Dict[str, Tuple[float, float]]],
            metric: str,
            clamp_non_negative: bool = True,
        ) -> np.ndarray:
            samples = np.zeros(n_samples)
            for stats in team_statistics:
                mean, std_dev = stats.get(metric, (0.0, 0.0))
                if std_dev <= 0:
                    team_samples = np.full(n_samples, mean, dtype=float)
                else:
                    team_samples = rng.normal(mean, std_dev, size=n_samples)
                if clamp_non_negative:
                    team_samples = np.clip(team_samples, 0.0, None)
                samples += team_samples
            return samples

        red_total_samples = _generate_alliance_samples(red_stats, "total_without_climb")
        blue_total_samples = _generate_alliance_samples(blue_stats, "total_without_climb")

        def _sample_alliance_climb(
            team_statistics: Sequence[Dict[str, Tuple[float, float]]]
        ) -> Tuple[np.ndarray, np.ndarray]:
            climb_points = np.zeros(n_samples)
            any_climb = np.zeros(n_samples, dtype=bool)

            for stats in team_statistics:
                climb_rate = float(stats.get("climb_rate", (0.0, 0.0))[0])
                if climb_rate <= 0.0:
                    continue
                probability = min(max(climb_rate, 0.0), 1.0)
                team_success = rng.random(n_samples) < probability
                if not np.any(team_success):
                    continue
                climb_points += team_success.astype(float) * 12.0
                any_climb = np.logical_or(any_climb, team_success)

            return climb_points, any_climb

        red_climb_points, red_any_climb = _sample_alliance_climb(red_stats)
        blue_climb_points, blue_any_climb = _sample_alliance_climb(blue_stats)

        red_total_samples += red_climb_points
        blue_total_samples += blue_climb_points

        red_win_pct = float(np.mean(red_total_samples > blue_total_samples))
        blue_win_pct = 1.0 - red_win_pct

        red_auto_coral_samples = _generate_alliance_samples(red_stats, "auto_coral")
        blue_auto_coral_samples = _generate_alliance_samples(blue_stats, "auto_coral")

        red_total_coral_samples = _generate_alliance_samples(red_stats, "total_coral")
        blue_total_coral_samples = _generate_alliance_samples(blue_stats, "total_coral")

        red_processor_samples = _generate_alliance_samples(red_stats, "processor")
        blue_processor_samples = _generate_alliance_samples(blue_stats, "processor")

        red_auto_rp = float(np.mean(red_auto_coral_samples >= 1.0))
        blue_auto_rp = float(np.mean(blue_auto_coral_samples >= 1.0))

        red_endgame_rp = float(np.mean(red_any_climb))
        blue_endgame_rp = float(np.mean(blue_any_climb))

        red_w_coral_rp = float(np.mean(red_total_coral_samples >= 27.0))
        blue_w_coral_rp = float(np.mean(blue_total_coral_samples >= 27.0))

        red_r_coral_rp = float(
            np.mean(
                np.logical_or(
                    np.logical_and(
                        red_total_coral_samples >= 15.0, red_processor_samples >= 2.0
                    ),
                    red_total_coral_samples >= 20.0,
                )
            )
        )
        blue_r_coral_rp = float(
            np.mean(
                np.logical_or(
                    np.logical_and(
                        blue_total_coral_samples >= 15.0, blue_processor_samples >= 2.0
                    ),
                    blue_total_coral_samples >= 20.0,
                )
            )
        )

        rp_predictions = {
            "red_auto_rp": red_auto_rp,
            "blue_auto_rp": blue_auto_rp,
            "red_endgame_rp": red_endgame_rp,
            "blue_endgame_rp": blue_endgame_rp,
            "red_w_coral_rp": red_w_coral_rp,
            "blue_w_coral_rp": blue_w_coral_rp,
            "red_r_coral_rp": red_r_coral_rp,
            "blue_r_coral_rp": blue_r_coral_rp,
        }

        for alliance_org_id in alliance_organization_ids:
            existing_prediction = await session.get(
                prediction_model,
                (event_code, int(match_number), match_level, alliance_org_id),
            )

            if existing_prediction is None:
                prediction_record = prediction_model(
                    season=season.id,
                    event_key=event_code,
                    match_number=int(match_number),
                    match_level=match_level,
                    organization_id=alliance_org_id,
                    red_alliance_win_pct=red_win_pct,
                    blue_alliance_win_pct=blue_win_pct,
                    n_samples=n_samples,
                )
                prediction_record.timestamp = now
            else:
                prediction_record = existing_prediction
                prediction_record.season = season.id
                prediction_record.red_alliance_win_pct = red_win_pct
                prediction_record.blue_alliance_win_pct = blue_win_pct
                prediction_record.n_samples = n_samples
                prediction_record.timestamp = now

            for field in RP_PREDICTION_FIELDS:
                value = rp_predictions.get(field, 0.5)
                if hasattr(prediction_record, field):
                    setattr(prediction_record, field, float(value))

            if hasattr(prediction_record, "updated_at"):
                setattr(prediction_record, "updated_at", now)

            session.add(prediction_record)

            results[alliance_org_id] = {
                "red_alliance_win_pct": red_win_pct,
                "blue_alliance_win_pct": blue_win_pct,
                **rp_predictions,
            }
            processed_organization_ids.add(alliance_org_id)

    await session.commit()

    return results
