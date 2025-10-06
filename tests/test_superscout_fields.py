import asyncio
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import app
from app.models import (
    FRCEvent,
    Organization,
    OrganizationEvent,
    Season,
    User,
    UserOrganization,
    UserRole,
)
from tests.conftest import AsyncSessionLocal


async def _prepare_superscout_context():
    async with AsyncSessionLocal() as session:
        season = Season(id=7, year=2025, name="REEFSCAPE")
        event = FRCEvent(
            event_key="2025super",
            event_name="Superscout Test Event",
            short_name="SuperTest",
            year=2025,
            week=3,
        )
        organization = Organization(name="Super Org", team_number=2468)
        user_id = uuid4()
        user = User(
            id=user_id,
            email="super@example.com",
            auth_provider="discord",
            display_name="Super User",
            logged_in_user_org=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        session.add_all([season, event, organization, user])
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

        organization_event = OrganizationEvent(
            organization_id=organization.id,
            event_key=event.event_key,
            public_data=True,
            active=True,
        )
        session.add(organization_event)
        await session.commit()

        return {
            "user_id": user_id,
            "membership_id": membership.id,
            "organization_id": organization.id,
            "event_key": event.event_key,
            "season_id": season.id,
        }


@pytest.fixture(scope="module")
def superscout_client(setup_database):
    data = asyncio.run(_prepare_superscout_context())

    async def override_current_user():
        return {
            "id": str(data["user_id"]),
            "displayName": "Super User",
            "email": "super@example.com",
            "user_org": data["membership_id"],
        }

    app.dependency_overrides[get_current_user] = override_current_user

    with TestClient(app) as client:
        client.test_context = data
        yield client

    app.dependency_overrides.pop(get_current_user, None)


def test_get_superscout_field_options(superscout_client):
    response = superscout_client.get("/scout/superscout/fields")
    assert response.status_code == 200
    assert response.json() == [
        {"key": "stopped_moving", "label": "Stopped Moving"},
        {"key": "dead_lt_45_seconds", "label": "Dead < 45 Seconds"},
        {"key": "dead_gt_45_seconds", "label": "Dead > 45 Seconds"},
        {"key": "slow_drive", "label": "Slow Drive"},
        {"key": "fast_drive", "label": "Fast Drive"},
        {"key": "good_driving", "label": "Good Driving"},
        {"key": "bad_driving", "label": "Bad Driving"},
        {"key": "drops_game_pieces", "label": "Drops Game Pieces"},
        {"key": "lots_of_fouls", "label": "Lots of Fouls"},
        {"key": "tipped", "label": "Tipped"},
        {"key": "didnt_move", "label": "Did Not Move"},
        {"key": "broken", "label": "Broken"},
        {"key": "no_show", "label": "No Show"},
        {"key": "dnp", "label": "DNP"},
        {"key": "played_defense", "label": "Played Defense"},
        {"key": "received_defense", "label": "Received Defense"},
        {"key": "yellow_card", "label": "Yellow Card"},
        {"key": "red_card", "label": "Red Card"},
        {"key": "floor_algae", "label": "Floor Algae"},
        {"key": "floor_coral", "label": "Floor Coral"},
        {"key": "holds_both_pieces", "label": "Holds Both Pieces"},
    ]


def test_create_superscout_record_auto_fields(superscout_client):
    payload = {
        "team_number": 111,
        "match_number": 1,
        "match_level": "qm",
        "robot_overall": 4,
        "timestamp": "2000-01-01T00:00:00Z",
    }

    response = superscout_client.post("/scout/superscout", json=payload)
    assert response.status_code == 201

    body = response.json()
    context = superscout_client.test_context

    assert body["event_key"] == context["event_key"]
    assert body["season"] == context["season_id"]
    assert body["user_id"] == str(context["user_id"])
    assert body["organization_id"] == context["organization_id"]
    assert body["notes"] == ""
    assert body["team_number"] == payload["team_number"]
    assert body["match_number"] == payload["match_number"]
    assert body["match_level"] == payload["match_level"]
    assert body["robot_overall"] == payload["robot_overall"]
    assert body["timestamp"] != payload["timestamp"]


def test_create_superscout_record_rejects_mismatched_event(superscout_client):
    payload = {
        "team_number": 111,
        "match_number": 2,
        "match_level": "qm",
        "robot_overall": 5,
        "event_key": "wrong_event",
    }

    response = superscout_client.post("/scout/superscout", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Superscout event does not match the active event for this user"
