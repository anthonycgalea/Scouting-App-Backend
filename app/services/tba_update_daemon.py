"""Utilities for automatically updating pending TBA match data."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.db.database import async_session_factory
from app.models import DataValidation, UserOrganization, UserRole, ValidationStatus
from app.services.scout import update_tba_match_data_for_pending_alliances

logger = logging.getLogger(__name__)

SLEEP_INTERVAL_SECONDS = 5 * 60


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional scope around a series of operations."""

    session: AsyncSession = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


async def _load_pending_organization_ids(session: AsyncSession) -> List[int]:
    """Return organization identifiers that have pending validations."""

    statement = (
        select(DataValidation.organization_id)
        .where(
            DataValidation.validation_status == ValidationStatus.PENDING,
            DataValidation.organization_id.is_not(None),
        )
        .distinct()
        .order_by(DataValidation.organization_id.asc())
    )

    result = await session.execute(statement)
    return [org_id for org_id, in result.all() if org_id is not None]


def _membership_priority(role: UserRole) -> int:
    """Return the priority used when selecting a membership for automation."""

    return {
        UserRole.ADMIN: 0,
        UserRole.LEAD: 1,
        UserRole.MEMBER: 2,
        UserRole.GUEST: 3,
        UserRole.PENDING: 4,
    }.get(role, 5)


async def _select_membership_for_org(
    session: AsyncSession, organization_id: int
) -> Optional[UserOrganization]:
    """Choose a suitable membership record for the given organization."""

    membership_result = await session.execute(
        select(UserOrganization).where(UserOrganization.organization_id == organization_id)
    )
    memberships: List[UserOrganization] = [
        membership
        for membership in membership_result.scalars().all()
        if membership is not None and membership.role != UserRole.PENDING
    ]

    if not memberships:
        return None

    memberships.sort(
        key=lambda membership: (
            _membership_priority(membership.role),
            membership.joined,
        )
    )
    return memberships[0]


def _build_user_payload(membership: UserOrganization) -> Dict[str, object]:
    """Construct the user payload expected by the scout service."""

    return {
        "id": str(membership.user_id),
        "displayName": "TBA Update Daemon",
        "email": "",
        "user_org": membership.id,
    }


async def process_pending_tba_updates() -> bool:
    """Process all pending TBA updates once.

    Returns ``True`` if any updates were applied.
    """

    async with session_scope() as session:
        organization_ids = await _load_pending_organization_ids(session)

    if not organization_ids:
        logger.info("No pending validations found for TBA update.")
        return False

    work_completed = False

    for organization_id in organization_ids:
        async with session_scope() as session:
            membership = await _select_membership_for_org(session, organization_id)
            if membership is None:
                logger.warning(
                    "Skipping organization %s because no memberships are available for TBA updates.",
                    organization_id,
                )
                continue

            user_payload = _build_user_payload(membership)

            try:
                results = await update_tba_match_data_for_pending_alliances(session, user_payload)
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

    return work_completed


__all__ = [
    "SLEEP_INTERVAL_SECONDS",
    "process_pending_tba_updates",
    "session_scope",
]

