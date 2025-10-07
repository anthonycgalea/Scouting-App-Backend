"""Services for working with match prediction data."""

from __future__ import annotations

from collections import defaultdict
from math import sqrt
from numbers import Number
from typing import Any, DefaultDict, Dict, List, Sequence, Set, Tuple, TypeVar

from fastapi import HTTPException
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import (
    MatchData,
    Prescout2025,
    UserOrganization,
)
from services.event import (
    MATCH_DATA_MODELS_BY_YEAR,
    get_active_event_key_for_user,
    get_event_or_404,
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
) -> List[RecordType]:
    collected: List[RecordType] = []
    unique_matches = len(seen_matches)

    for record in records:
        match_identifier = (record.match_level, record.match_number)
        if match_identifier in seen_matches:
            collected.append(record)
            continue

        if unique_matches >= limit:
            break

        seen_matches.add(match_identifier)
        unique_matches += 1
        collected.append(record)

    return collected


async def _fetch_match_records(
    session: AsyncSession,
    model: type[RecordType],
    event_key: str,
    organization_id: int,
) -> List[RecordType]:
    statement = (
        select(model)
        .where(
            model.event_key == event_key,
            model.organization_id == organization_id,
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

    seen_matches: Set[Tuple[str, int]] = set()
    ordered_records: List[MatchData] = []
    limit = 10

    if match_model is not None:
        scouted_records = await _fetch_match_records(
            session, match_model, event_key, membership.organization_id
        )
        ordered_records.extend(
            _collect_latest_matches(scouted_records, seen_matches, limit)
        )

    if len(seen_matches) < limit and prescout_model is not None:
        prescout_records = await _fetch_match_records(
            session, prescout_model, event_key, membership.organization_id
        )
        ordered_records.extend(
            _collect_latest_matches(prescout_records, seen_matches, limit)
        )

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
