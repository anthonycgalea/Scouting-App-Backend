import asyncio
import os
from datetime import datetime
from uuid import uuid4

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import app
from app.models import (
    FRCEvent,
    Organization,
    OrganizationEvent,
    User,
    UserOrganization,
    UserRole,
)
from tests.conftest import AsyncSessionLocal


async def _create_user():
    async with AsyncSessionLocal() as session:
        user_id = uuid4()
        email = "user@example.com"
        user = User(
            id=user_id,
            email=email,
            auth_provider="discord",
            display_name="Original Name",
            logged_in_user_org=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        session.add(user)
        await session.commit()

        return {"user_id": user_id, "email": email}


async def _create_user_with_membership(
    *,
    role: UserRole = UserRole.MEMBER,
    event_key: str = "2024test",
    active_event: bool = True,
):
    async with AsyncSessionLocal() as session:
        user_id = uuid4()
        email = "member@example.com"
        user = User(
            id=user_id,
            email=email,
            auth_provider="discord",
            display_name="Original Name",
            logged_in_user_org=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        organization = Organization(name="Test Org", team_number=1234)
        event = FRCEvent(
            event_key=event_key,
            event_name="Test Event",
            year=2024,
            week=1,
            short_name="Test",
        )

        session.add_all([user, organization, event])
        await session.flush()

        membership = UserOrganization(
            user_id=user_id,
            organization_id=organization.id,
            role=role,
            event_key=event_key if role == UserRole.GUEST else None,
        )
        session.add(membership)
        await session.flush()

        user.logged_in_user_org = membership.id
        session.add(user)

        if active_event:
            organization_event = OrganizationEvent(
                organization_id=organization.id,
                event_key=event_key,
                public_data=False,
                active=True,
            )
            session.add(organization_event)

        await session.commit()

        return {
            "user_id": user_id,
            "email": email,
            "membership_id": membership.id,
            "event_key": event_key,
        }


@pytest.fixture
def user_client(setup_database):
    user_data = asyncio.run(_create_user())

    async def override_current_user():
        return {
            "id": str(user_data["user_id"]),
            "displayName": "Original Name",
            "email": user_data["email"],
            "user_org": None,
        }

    app.dependency_overrides[get_current_user] = override_current_user

    with TestClient(app) as client:
        yield client, user_data

    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def user_client_with_event(setup_database):
    user_data = asyncio.run(_create_user_with_membership())

    async def override_current_user():
        return {
            "id": str(user_data["user_id"]),
            "displayName": "Original Name",
            "email": user_data["email"],
            "user_org": user_data["membership_id"],
        }

    app.dependency_overrides[get_current_user] = override_current_user

    with TestClient(app) as client:
        yield client, user_data

    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def guest_user_client(setup_database):
    user_data = asyncio.run(
        _create_user_with_membership(
            role=UserRole.GUEST,
            event_key="2024guest",
            active_event=False,
        )
    )

    async def override_current_user():
        return {
            "id": str(user_data["user_id"]),
            "displayName": "Original Name",
            "email": user_data["email"],
            "user_org": user_data["membership_id"],
        }

    app.dependency_overrides[get_current_user] = override_current_user

    with TestClient(app) as client:
        yield client, user_data

    app.dependency_overrides.pop(get_current_user, None)


def test_update_display_name(user_client):
    client, data = user_client

    response = client.patch("/user/info", json={"display_name": "Anthony"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["displayName"] == "Anthony"
    assert payload["id"] == str(data["user_id"])

    async def _fetch_user():
        async with AsyncSessionLocal() as session:
            return await session.get(User, data["user_id"])

    updated_user = asyncio.run(_fetch_user())
    assert updated_user.display_name == "Anthony"


def test_update_display_name_rejects_blank(user_client):
    client, data = user_client

    response = client.patch("/user/info", json={"display_name": "   "})
    assert response.status_code == 422
    assert response.json()["detail"] == "Display name cannot be empty"

    async def _fetch_user():
        async with AsyncSessionLocal() as session:
            return await session.get(User, data["user_id"])

    updated_user = asyncio.run(_fetch_user())
    assert updated_user.display_name == "Original Name"


def test_get_user_event(user_client_with_event):
    client, data = user_client_with_event

    response = client.get("/user/event")
    assert response.status_code == 200
    assert response.json() == {"eventCode": data["event_key"]}


def test_get_user_event_for_guest(guest_user_client):
    client, data = guest_user_client

    response = client.get("/user/event")
    assert response.status_code == 200
    assert response.json() == {"eventCode": data["event_key"]}
