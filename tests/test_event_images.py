import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

APP_PATH = Path(__file__).resolve().parents[1] / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

from auth.dependencies import get_current_user
from app.main import app
from models import (
    FRCEvent,
    Organization,
    OrganizationEvent,
    RobotEventImageLink,
    TeamRecord,
    User,
    UserOrganization,
    UserRole,
)
from db.database import get_session as core_get_session
from tests.conftest import AsyncSessionLocal


async def _prepare_event_images_data():
    async with AsyncSessionLocal() as session:
        event = FRCEvent(
            event_key="2024images",
            event_name="Images Event",
            short_name="Images",
            year=2024,
            week=3,
        )
        other_event = FRCEvent(
            event_key="2024other",
            event_name="Other Event",
            short_name="Other",
            year=2024,
            week=4,
        )
        organization = Organization(name="Images Org", team_number=1234)
        user_id = uuid4()
        now = datetime.utcnow()
        user = User(
            id=user_id,
            email="images@example.com",
            auth_provider="discord",
            display_name="Image User",
            logged_in_user_org=None,
            created_at=now,
            updated_at=now,
        )
        team_one = TeamRecord(teamNumber=1111, teamName="Team 1111")
        team_two = TeamRecord(teamNumber=2222, teamName="Team 2222")
        team_without_images = TeamRecord(teamNumber=3333, teamName="Team 3333")

        session.add_all(
            [
                event,
                other_event,
                organization,
                user,
                team_one,
                team_two,
                team_without_images,
            ]
        )
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

        org_event = OrganizationEvent(
            organization_id=organization.id,
            event_key=event.event_key,
            public_data=True,
            active=True,
        )
        session.add(org_event)
        await session.commit()

        image_time = datetime.utcnow()
        images = [
            RobotEventImageLink(
                team_number=team_one.team_number,
                event_key=event.event_key,
                image_url="https://cdn.example.com/team1111-latest.jpg",
                uploaded_at=image_time,
            ),
            RobotEventImageLink(
                team_number=team_one.team_number,
                event_key=event.event_key,
                image_url="https://cdn.example.com/team1111-older.jpg",
                uploaded_at=image_time - timedelta(minutes=10),
            ),
            RobotEventImageLink(
                team_number=team_two.team_number,
                event_key=event.event_key,
                image_url="https://cdn.example.com/team2222.jpg",
                uploaded_at=image_time,
            ),
            RobotEventImageLink(
                team_number=team_one.team_number,
                event_key=other_event.event_key,
                image_url="https://cdn.example.com/team1111-other-event.jpg",
                uploaded_at=image_time,
            ),
        ]
        session.add_all(images)
        await session.commit()

        return {
            "user_id": user_id,
            "membership_id": membership.id,
            "team_one": team_one.team_number,
            "team_two": team_two.team_number,
            "team_without_images": team_without_images.team_number,
        }


@pytest.fixture(scope="module")
def prepared_event_images_data(setup_database):
    return asyncio.run(_prepare_event_images_data())


@pytest.fixture
def event_images_client(prepared_event_images_data):
    data = prepared_event_images_data

    async def override_session():
        async with AsyncSessionLocal() as session:
            yield session

    async def override_current_user():
        return {
            "id": str(data["user_id"]),
            "displayName": "Image User",
            "email": "images@example.com",
            "user_org": data["membership_id"],
        }

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[core_get_session] = override_session

    with TestClient(app) as client:
        yield client, data

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(core_get_session, None)


def test_event_images_endpoint_returns_grouped_links(event_images_client):
    client, data = event_images_client

    response = client.get("/event/images")
    assert response.status_code == 200

    payload = response.json()
    assert len(payload) == 2

    team_numbers = [entry["teamNumber"] for entry in payload]
    assert data["team_without_images"] not in team_numbers

    expected = {
        data["team_one"]: [
            "https://cdn.example.com/team1111-latest.jpg",
            "https://cdn.example.com/team1111-older.jpg",
        ],
        data["team_two"]: ["https://cdn.example.com/team2222.jpg"],
    }

    for entry in payload:
        assert entry["images"] == expected[entry["teamNumber"]]

    assert "https://cdn.example.com/team1111-other-event.jpg" not in {
        image for entry in payload for image in entry["images"]
    }
