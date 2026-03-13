import asyncio
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import app
from app.models import Organization, User, UserOrganization, UserRole
from tests.conftest import AsyncSessionLocal


async def _prepare_guest_membership_user():
    async with AsyncSessionLocal() as session:
        organization = Organization(name="Guest Picklist Org", team_number=9000)
        user_id = uuid4()
        user = User(
            id=user_id,
            email="guest-picklist@example.com",
            auth_provider="discord",
            display_name="Guest Picklist User",
            logged_in_user_org=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        session.add_all([organization, user])
        await session.commit()
        await session.refresh(organization)

        membership = UserOrganization(
            user_id=user_id,
            organization_id=organization.id,
            role=UserRole.MEMBER,
        )
        session.add(membership)
        await session.commit()
        await session.refresh(membership)

        return user_id, membership.id


@pytest.fixture(scope="module")
def guest_membership_user(setup_database):
    return asyncio.run(_prepare_guest_membership_user())


def test_list_picklists_returns_empty_for_non_lead_members(guest_membership_user):
    user_id, membership_id = guest_membership_user

    async def override_current_user():
        return {
            "id": str(user_id),
            "displayName": "Guest Picklist User",
            "email": "guest-picklist@example.com",
            "user_org": membership_id,
        }

    app.dependency_overrides[get_current_user] = override_current_user

    with TestClient(app) as client:
        response = client.get("/picklists")

    app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    assert response.json() == []
