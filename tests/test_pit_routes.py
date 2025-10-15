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
    TeamRecord,
    User,
    UserOrganization,
    UserRole,
)
from tests.conftest import AsyncSessionLocal


async def _prepare_pit_scouting_data():
    async with AsyncSessionLocal() as session:
        season = Season(id=5, year=2025, name="REEFSCAPE")
        event = FRCEvent(
            event_key="2025pit",
            event_name="Pit Testing Event",
            short_name="PitTest",
            year=2025,
            week=2,
        )
        organization = Organization(name="Pit Org", team_number=1357)
        user_id = uuid4()
        user = User(
            id=user_id,
            email="pit@example.com",
            auth_provider="discord",
            display_name="Pit User",
            logged_in_user_org=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        team = TeamRecord(teamNumber=9999, teamName="Team 9999")
        extra_teams = [
            TeamRecord(teamNumber=8888, teamName="Team 8888"),
            TeamRecord(teamNumber=7777, teamName="Team 7777"),
        ]

        session.add_all([season, event, organization, user, team, *extra_teams])
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
            "event_key": event.event_key,
            "organization_id": organization.id,
            "season_id": season.id,
            "team_number": team.teamNumber,
            "extra_team_numbers": [team.teamNumber for team in extra_teams],
        }


@pytest.fixture(scope="module")
def prepared_pit_scouting_data(setup_database):
    return asyncio.run(_prepare_pit_scouting_data())


@pytest.fixture
def pit_client(prepared_pit_scouting_data):
    data = prepared_pit_scouting_data

    async def override_current_user():
        return {
            "id": str(data["user_id"]),
            "displayName": "Pit User",
            "email": "pit@example.com",
            "user_org": data["membership_id"],
        }

    app.dependency_overrides[get_current_user] = override_current_user

    with TestClient(app) as client:
        yield client, data

    app.dependency_overrides.pop(get_current_user, None)


def test_pit_scout_crud_flow(pit_client):
    client, data = pit_client

    pit_payload = {
        "team_number": data["team_number"],
        "notes": "Initial pit notes",
        "robot_weight": 120,
        "drivetrain": "SWERVE",
        "autoCoralCount": 3,
        "teleNotes": "Handles coral well",
        "overallNotes": "Strong pit presence",
    }

    create_response = client.post("/scout/pit", json=pit_payload)
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["team_number"] == data["team_number"]
    assert created["drivetrain"] == "SWERVE"
    assert created["event_key"] == data["event_key"]
    assert created["season"] == data["season_id"]

    list_response = client.get("/scout/pit")
    assert list_response.status_code == 200
    records = list_response.json()
    assert len(records) == 1
    assert records[0]["autoCoralCount"] == 3
    assert records[0]["event_key"] == data["event_key"]

    update_payload = {**pit_payload, "autoCoralCount": 4, "teleNotes": "Updated tele notes"}
    update_response = client.patch("/scout/pit", json=update_payload)
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["autoCoralCount"] == 4
    assert updated["teleNotes"] == "Updated tele notes"
    assert updated["event_key"] == data["event_key"]
    assert updated["season"] == data["season_id"]

    delete_response = client.request("DELETE", "/scout/pit", json={"team_number": pit_payload["team_number"]})
    assert delete_response.status_code == 204

    final_list = client.get("/scout/pit")
    assert final_list.status_code == 200
    assert final_list.json() == []


def test_pit_scout_batch_submission(pit_client):
    client, data = pit_client

    batch_payload = [
        {
            "team_number": team_number,
            "notes": f"Pit notes for {team_number}",
            "robot_weight": 110 + index,
            "drivetrain": "SWERVE",
            "autoCoralCount": index,
            "teleNotes": f"Tele notes {team_number}",
            "overallNotes": f"Overall notes {team_number}",
        }
        for index, team_number in enumerate(data["extra_team_numbers"], start=1)
    ]

    response = client.post("/scout/pit/batch", json=batch_payload)
    assert response.status_code == 200

    list_response = client.get("/scout/pit")
    assert list_response.status_code == 200
    records = list_response.json()
    assert len(records) == len(batch_payload)
    returned_team_numbers = {record["team_number"] for record in records}
    assert returned_team_numbers == set(data["extra_team_numbers"])

    for team_number in data["extra_team_numbers"]:
        delete_response = client.request(
            "DELETE", "/scout/pit", json={"team_number": team_number}
        )
        assert delete_response.status_code == 204
