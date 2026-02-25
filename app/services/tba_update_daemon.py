"""Utilities for automatically updating pending TBA match data."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlmodel import select

from app.db.database import async_session_factory
from app.models import (
    DataValidation,
    OrganizationEvent,
    UserOrganization,
    UserRole,
    ValidationStatus,
)
from app.services.event import (
    get_active_event_key_for_user,
    get_event_or_404,
    get_scouting_alliance_organization_ids,
)
from app.services.scout import update_tba_match_data_for_pending_alliances

logger = logging.getLogger(__name__)

SLEEP_INTERVAL_SECONDS = 5 * 60


@dataclass(frozen=True)
class MembershipSnapshot:
    """Immutable data describing an organization membership."""

    id: int
    user_id: UUID
    organization_id: int
    role: UserRole
    joined: datetime
    event_key: Optional[str]


@dataclass(frozen=True)
class PendingOrganizationWork:
    """Metadata describing pending validations for an organization."""

    organization_id: int
    latest_pending: datetime
    membership: Optional[MembershipSnapshot]


@dataclass
class OrganizationProcessingState:
    """Cached state retained between daemon iterations."""

    latest_pending_timestamp: datetime
    membership_signature: Optional[Tuple[int, UserRole, datetime]]
    user_payload: Dict[str, object]
    event_key: Optional[str]
    event_year: Optional[int]
    alliance_organization_ids: Optional[Tuple[int, ...]]


_organization_state_cache: Dict[int, OrganizationProcessingState] = {}


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional scope around a series of operations."""

    session: AsyncSession = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


async def _load_pending_organization_work(
    session: AsyncSession,
) -> List[PendingOrganizationWork]:
    """Return active organization-event metadata grouped by organization."""

    membership_priority = case(
        (UserOrganization.role == UserRole.ADMIN, 0),
        (UserOrganization.role == UserRole.LEAD, 1),
        (UserOrganization.role == UserRole.MEMBER, 2),
        (UserOrganization.role == UserRole.GUEST, 3),
        else_=4,
    )

    pending_orgs_subquery = (
        select(
            DataValidation.organization_id.label("org_id"),
            func.max(DataValidation.timestamp).label("latest_pending"),
        )
        .where(
            DataValidation.validation_status == ValidationStatus.PENDING,
            DataValidation.organization_id.is_not(None),
        )
        .group_by(DataValidation.organization_id)
        .subquery()
    )

    active_orgs_subquery = (
        select(OrganizationEvent.organization_id.label("org_id"))
        .where(OrganizationEvent.active.is_(True))
        .distinct()
        .subquery()
    )

    ranked_memberships = (
        select(
            UserOrganization.id,
            UserOrganization.user_id,
            UserOrganization.organization_id,
            UserOrganization.role,
            UserOrganization.joined,
            UserOrganization.event_key,
            func.row_number()
            .over(
                partition_by=UserOrganization.organization_id,
                order_by=(membership_priority, UserOrganization.joined),
            )
            .label("priority_rank"),
        )
        .where(UserOrganization.role != UserRole.PENDING)
        .subquery()
    )

    membership_alias = aliased(UserOrganization, ranked_memberships)

    statement = (
        select(
            active_orgs_subquery.c.org_id,
            pending_orgs_subquery.c.latest_pending,
            membership_alias,
        )
        .outerjoin(
            pending_orgs_subquery,
            pending_orgs_subquery.c.org_id == active_orgs_subquery.c.org_id,
        )
        .outerjoin(
            membership_alias,
            membership_alias.organization_id == active_orgs_subquery.c.org_id,
        )
        .where(
            or_(
                membership_alias.priority_rank == 1,
                membership_alias.priority_rank.is_(None),
            )
        )
        .order_by(active_orgs_subquery.c.org_id.asc())
    )

    result = await session.execute(statement)

    work_items: List[PendingOrganizationWork] = []
    for org_id, latest_pending, membership in result.all():
        if org_id is None:
            continue

        membership_snapshot: Optional[MembershipSnapshot] = None
        if membership is not None:
            membership_snapshot = MembershipSnapshot(
                id=int(membership.id),
                user_id=membership.user_id,
                organization_id=int(membership.organization_id),
                role=membership.role,
                joined=membership.joined,
                event_key=membership.event_key,
            )

        work_items.append(
            PendingOrganizationWork(
                organization_id=int(org_id),
                latest_pending=latest_pending or datetime.min,
                membership=membership_snapshot,
            )
        )

    return work_items


def _build_user_payload(membership: MembershipSnapshot) -> Dict[str, object]:
    """Construct the user payload expected by the scout service."""

    return {
        "id": str(membership.user_id),
        "displayName": "TBA Update Daemon",
        "email": "",
        "user_org": membership.id,
    }


def _snapshot_to_membership_model(snapshot: MembershipSnapshot) -> UserOrganization:
    """Materialize a ``UserOrganization`` instance from a cached snapshot."""

    return UserOrganization(
        id=snapshot.id,
        user_id=snapshot.user_id,
        organization_id=snapshot.organization_id,
        role=snapshot.role,
        joined=snapshot.joined,
        event_key=snapshot.event_key,
    )


async def process_pending_tba_updates() -> bool:
    """Process all pending TBA updates once.

    Returns ``True`` if any updates were applied.
    """

    async with session_scope() as session:
        pending_work = await _load_pending_organization_work(session)

        if not pending_work:
            logger.info("No pending validations found for TBA update.")
            _organization_state_cache.clear()
            return False

        active_org_ids = {work.organization_id for work in pending_work}
        stale_org_ids = [
            cached_org_id
            for cached_org_id in _organization_state_cache
            if cached_org_id not in active_org_ids
        ]
        for stale_org_id in stale_org_ids:
            _organization_state_cache.pop(stale_org_id, None)

        work_completed = False

        for work in pending_work:
            membership = work.membership
            organization_id = work.organization_id
            latest_pending = work.latest_pending
            cache_entry = _organization_state_cache.get(organization_id)

            membership_signature: Optional[Tuple[int, UserRole, datetime]] = None
            if membership is not None:
                membership_signature = (
                    membership.id,
                    membership.role,
                    membership.joined,
                )

            if membership is None:
                if cache_entry is None or cache_entry.membership_signature is not None:
                    logger.warning(
                        "Skipping organization %s because no memberships are available for TBA updates.",
                        organization_id,
                    )
                _organization_state_cache[organization_id] = OrganizationProcessingState(
                    latest_pending_timestamp=latest_pending,
                    membership_signature=None,
                    user_payload={},
                    event_key=None,
                    event_year=None,
                    alliance_organization_ids=None,
                )
                continue

            if (
                cache_entry is not None
                and cache_entry.membership_signature == membership_signature
                and cache_entry.user_payload
            ):
                user_payload = cache_entry.user_payload
            else:
                user_payload = _build_user_payload(membership)

            if (
                cache_entry is not None
                and cache_entry.membership_signature == membership_signature
                and cache_entry.event_key
            ):
                event_key = cache_entry.event_key
            else:
                event_key = await get_active_event_key_for_user(session, user_payload)

            if (
                cache_entry is not None
                and cache_entry.membership_signature == membership_signature
                and cache_entry.event_year is not None
            ):
                event_year = cache_entry.event_year
            else:
                event = await get_event_or_404(session, event_key)
                event_year = event.year

            if (
                cache_entry is not None
                and cache_entry.membership_signature == membership_signature
                and cache_entry.alliance_organization_ids is not None
            ):
                alliance_ids = cache_entry.alliance_organization_ids
            else:
                alliance_id_set = await get_scouting_alliance_organization_ids(
                    session, event_key, membership.organization_id
                )
                alliance_ids = tuple(sorted(int(org_id) for org_id in alliance_id_set))

            try:
                results = await update_tba_match_data_for_pending_alliances(
                    session,
                    user_payload,
                    membership_override=_snapshot_to_membership_model(membership),
                    event_key_override=event_key,
                    event_year_override=event_year,
                    alliance_ids_override=alliance_ids,
                )
            except HTTPException as exc:
                logger.warning(
                    "TBA update failed for organization %s: %s",
                    organization_id,
                    exc.detail,
                )
                await session.rollback()
            except Exception:
                logger.exception(
                    "Unexpected error while updating TBA data for organization %s.",
                    organization_id,
                )
                await session.rollback()
            else:
                updated_counts = (
                    results.get("updated_matches", 0),
                    results.get("updated_alliances", 0),
                    results.get("updated_validations", 0),
                )

                if any(count for count in updated_counts):
                    work_completed = True

                logger.info(
                    "Completed TBA update for organization %s: %s",
                    organization_id,
                    results,
                )

                _organization_state_cache[organization_id] = OrganizationProcessingState(
                    latest_pending_timestamp=latest_pending,
                    membership_signature=membership_signature,
                    user_payload=user_payload,
                    event_key=event_key,
                    event_year=event_year,
                    alliance_organization_ids=alliance_ids,
                )

        return work_completed


__all__ = [
    "SLEEP_INTERVAL_SECONDS",
    "process_pending_tba_updates",
    "session_scope",
]
