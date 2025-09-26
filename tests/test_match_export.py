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
    Endgame2025,
    FRCEvent,
    MatchData2025,
    Organization,
    OrganizationEvent,
    Season,
    TeamRecord,
    User,
    UserOrganization,
    UserRole,
)
from tests.conftest import AsyncSessionLocal


async def _prepare_match_data():
    async with AsyncSessionLocal() as session:
        season = Season(id=1, year=2025, name="REEFSCAPE")
        event = FRCEvent(
            event_key="2025export",
            event_name="Export Event",
            short_name="Export",
            year=2025,
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
        ]

        session.add_all([season, event, organization, user, *teams])
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

        match_data = [
            MatchData2025(
                season=season.id,
                team_number=1111,
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                notes="First match notes",
                al4c=2,
                al3c=1,
                tl4c=3,
                tNet=1,
                endgame=Endgame2025.SHALLOW,
            ),
            MatchData2025(
                season=season.id,
                team_number=2222,
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                notes="Second match notes",
                al4c=1,
                tl2c=2,
                aNet=1,
                tProcessor=2,
                endgame=Endgame2025.DEEP,
            ),
        ]

        session.add(organization_event)
        session.add_all(match_data)
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


def test_export_match_data_as_csv(authorized_client):
    client, event_key = authorized_client
    response = client.post("/organization/downloadData", json={"file_type": "csv"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].endswith(f'{event_key}_match_data.csv"')

    rows = response.text.strip().splitlines()
    assert len(rows) == 3  # header + two matches
    assert "match_number" in rows[0]
    assert "First match notes" in rows[1]


def test_export_match_data_as_json(authorized_client):
    client, event_key = authorized_client
    response = client.post("/organization/downloadData", json={"file_type": "json"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["content-disposition"].endswith(f'{event_key}_match_data.json"')

    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 2
    assert all(item["event_key"] == event_key for item in payload)
    assert payload[0]["endgame"] in {"SHALLOW", "DEEP"}
    assert all(isinstance(item["user_id"], str) for item in payload)


def test_export_match_data_as_xls(authorized_client):
    client, event_key = authorized_client
    response = client.post("/organization/downloadData", json={"file_type": "xls"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.ms-excel")
    assert response.headers["content-disposition"].endswith(f'{event_key}_match_data.xls"')
    assert "<table" in response.text
    assert "First match notes" in response.text


def test_export_match_data_with_invalid_type(authorized_client):
    client, _ = authorized_client
    response = client.post("/organization/downloadData", json={"file_type": "txt"})

    assert response.status_code == 422
