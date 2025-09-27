import asyncio
import os
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

from app.main import app  # noqa: E402
from app.auth.dependencies import get_current_user  # noqa: E402
from app.models import (  # noqa: E402
    DataValidation,
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
    ValidationStatus,
)
from tests.conftest import AsyncSessionLocal  # noqa: E402


async def _prepare_match_data_for_validation():
    async with AsyncSessionLocal() as session:
        season = Season(id=1, year=2025, name="REEFSCAPE")
        event = FRCEvent(
            event_key="2025validate",
            event_name="Validation Event",
            short_name="Validate",
            year=2025,
            week=1,
        )
        organization = Organization(name="Validation Org", team_number=4321)
        user_id = uuid4()
        user = User(
            id=user_id,
            email="validate@example.com",
            auth_provider="discord",
            display_name="Validator",
            logged_in_user_org=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        team = TeamRecord(teamNumber=7777, teamName="Team 7777")

        session.add_all([season, event, organization, user, team])
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

        match_data = MatchData2025(
            season=season.id,
            team_number=team.teamNumber,
            event_key=event.event_key,
            match_number=1,
            match_level="qm",
            user_id=user_id,
            organization_id=organization.id,
            notes="Initial notes",
            al4c=1,
            tl4c=1,
            aNet=1,
            tProcessor=1,
            endgame=Endgame2025.PARK,
        )

        session.add(organization_event)
        session.add(match_data)
        await session.commit()

        return {
            "user_id": user_id,
            "membership_id": membership.id,
            "event_key": event.event_key,
            "organization_id": organization.id,
            "team_number": team.teamNumber,
            "season_id": season.id,
        }


@pytest.fixture(scope="module")
def prepared_validation_data(setup_database):
    return asyncio.run(_prepare_match_data_for_validation())


@pytest.fixture
def authorized_validation_client(prepared_validation_data):
    data = prepared_validation_data

    async def override_current_user():
        return {
            "id": str(data["user_id"]),
            "displayName": "Validator",
            "email": "validate@example.com",
            "user_org": data["membership_id"],
        }

    app.dependency_overrides[get_current_user] = override_current_user

    with TestClient(app) as client:
        yield client, data

    app.dependency_overrides.pop(get_current_user, None)


def test_put_data_validation_updates_match_and_status(authorized_validation_client):
    client, data = authorized_validation_client

    payload = {
        "season": data["season_id"],
        "team_number": data["team_number"],
        "event_key": data["event_key"],
        "match_number": 1,
        "match_level": "qm",
        "user_id": str(data["user_id"]),
        "organization_id": data["organization_id"],
        "notes": "Corrected notes",
        "al4c": 5,
        "al3c": 0,
        "al2c": 0,
        "al1c": 0,
        "tl4c": 4,
        "tl3c": 0,
        "tl2c": 0,
        "tl1c": 0,
        "aNet": 2,
        "tNet": 0,
        "aProcessor": 1,
        "tProcessor": 3,
        "endgame": "DEEP",
    }

    response = client.put("/scout/dataValidation", json=payload)
    assert response.status_code == 200

    body = response.json()
    assert body["validation_status"] == ValidationStatus.VALID.value

    async def _fetch_records():
        async with AsyncSessionLocal() as session:
            match_stmt = select(MatchData2025).where(
                MatchData2025.event_key == data["event_key"],
                MatchData2025.match_number == 1,
                MatchData2025.match_level == "qm",
                MatchData2025.team_number == data["team_number"],
                MatchData2025.user_id == data["user_id"],
            )
            match_result = await session.execute(match_stmt)
            updated_match = match_result.scalars().first()

            validation_stmt = select(DataValidation).where(
                DataValidation.event_key == data["event_key"],
                DataValidation.match_number == 1,
                DataValidation.match_level == "qm",
                DataValidation.team_number == data["team_number"],
                DataValidation.user_id == data["user_id"],
            )
            validation_result = await session.execute(validation_stmt)
            validation = validation_result.scalars().first()

            return updated_match, validation

    updated_match, validation = asyncio.run(_fetch_records())

    assert updated_match is not None
    assert updated_match.al4c == 5
    assert updated_match.tl4c == 4
    assert updated_match.aNet == 2
    assert updated_match.tProcessor == 3
    assert updated_match.endgame == Endgame2025.DEEP
    assert updated_match.notes == "Initial notes"

    assert validation is not None
    assert validation.validation_status == ValidationStatus.VALID
    assert validation.notes == "Corrected notes"
