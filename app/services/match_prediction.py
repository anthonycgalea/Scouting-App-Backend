"""Services for working with match prediction data."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Set, Tuple, TypeVar

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
