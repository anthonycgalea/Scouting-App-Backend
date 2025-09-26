import asyncio
import os
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

from app.main import app
from app.auth.dependencies import get_current_user
from app.models import (
    FRCEvent,
    MatchSchedule,
    Organization,
    OrganizationEvent,
    TeamRecord,
    User,
    UserOrganization,
    UserRole,
)
from tests.conftest import AsyncSessionLocal


async def _prepare_match_data():
    async with AsyncSessionLocal() as session:
        event = FRCEvent(
            event_key="2024export",
            event_name="Export Event",
            short_name="Export",
            year=2024,
            week=1,
        )
        organization = Organization(name="Export Org", team_number=9999)
        user_id = uuid4()
        user = User(
            id=user_id,
            email="export@example.com",
            auth_provider="discord",
            display_name="Export User",
            logged_in_user_org=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        teams = [
            TeamRecord(teamNumber=1111, teamName="Team 1111"),
            TeamRecord(teamNumber=2222, teamName="Team 2222"),
            TeamRecord(teamNumber=3333, teamName="Team 3333"),
            TeamRecord(teamNumber=4444, teamName="Team 4444"),
            TeamRecord(teamNumber=5555, teamName="Team 5555"),
            TeamRecord(teamNumber=6666, teamName="Team 6666"),
            TeamRecord(teamNumber=7777, teamName="Team 7777"),
            TeamRecord(teamNumber=8888, teamName="Team 8888"),
            TeamRecord(teamNumber=9998, teamName="Team 9998"),
        ]

        session.add_all([event, organization, user, *teams])
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

        matches = [
            MatchSchedule(
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                red1_id=1111,
                red2_id=2222,
                red3_id=3333,
                blue1_id=4444,
                blue2_id=5555,
                blue3_id=6666,
            ),
            MatchSchedule(
                event_key=event.event_key,
                match_number=2,
                match_level="qm",
                red1_id=7777,
                red2_id=8888,
                red3_id=9998,
                blue1_id=1111,
                blue2_id=2222,
                blue3_id=3333,
            ),
        ]

        session.add(organization_event)
        session.add_all(matches)
        await session.commit()

        return user_id, membership.id, event.event_key


@pytest.fixture(scope="module")
def prepared_match_export_data(setup_database):
    return asyncio.run(_prepare_match_data())


@pytest.fixture
def authorized_client(prepared_match_export_data):
    user_id, membership_id, event_key = prepared_match_export_data

    async def override_current_user():
        return {
            "id": str(user_id),
            "displayName": "Export User",
            "email": "export@example.com",
            "user_org": membership_id,
        }

    app.dependency_overrides[get_current_user] = override_current_user

    with TestClient(app) as client:
        yield client, event_key

    app.dependency_overrides.pop(get_current_user, None)


def test_export_matches_as_csv(authorized_client):
    client, event_key = authorized_client
    response = client.post("/event/matches/export", json={"file_type": "csv"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].endswith(f'{event_key}_matches.csv"')

    rows = response.text.strip().splitlines()
    assert len(rows) == 3  # header + two matches
    assert "match_number" in rows[0]
    assert "qm" in rows[1]


def test_export_matches_as_json(authorized_client):
    client, event_key = authorized_client
    response = client.post("/event/matches/export", json={"file_type": "json"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["content-disposition"].endswith(f'{event_key}_matches.json"')

    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 2
    assert all(item["event_key"] == event_key for item in payload)


def test_export_matches_as_xls(authorized_client):
    client, event_key = authorized_client
    response = client.post("/event/matches/export", json={"file_type": "xls"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.ms-excel")
    assert response.headers["content-disposition"].endswith(f'{event_key}_matches.xls"')
    assert "<table" in response.text
    assert "Team 1111" in response.text


def test_export_matches_with_invalid_type(authorized_client):
    client, _ = authorized_client
    response = client.post("/event/matches/export", json={"file_type": "txt"})

    assert response.status_code == 422
