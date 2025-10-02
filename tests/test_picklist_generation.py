import asyncio
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import app
from app.models import (
    Endgame2025,
    FRCEvent,
    MatchData2025,
    Organization,
    OrganizationEvent,
    PickListGenerator2025,
    Season,
    TeamEvent,
    TeamRecord,
    User,
    UserOrganization,
    UserRole,
)
from tests.conftest import AsyncSessionLocal


async def _prepare_picklist_generation_data():
    async with AsyncSessionLocal() as session:
        season = Season(id=3, year=2025, name="REEFSCAPE")
        event = FRCEvent(
            event_key="2025picklist",
            event_name="Picklist Event",
            short_name="Picklist",
            year=2025,
            week=3,
        )
        organization = Organization(name="Picklist Org", team_number=2468)
        user_id = uuid4()
        user = User(
            id=user_id,
            email="picklist@example.com",
            auth_provider="discord",
            display_name="Picklist User",
            logged_in_user_org=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        teams = [
            TeamRecord(teamNumber=3333, teamName="Team 3333"),
            TeamRecord(teamNumber=4444, teamName="Team 4444"),
        ]

        session.add_all([season, event, organization, user, *teams])
        await session.commit()
        await session.refresh(organization)

        membership = UserOrganization(
            user_id=user_id,
            organization_id=organization.id,
            role=UserRole.LEAD,
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

        team_entries = [
            TeamEvent(event_key=event.event_key, team_number=3333),
            TeamEvent(event_key=event.event_key, team_number=4444),
        ]

        match_data = [
            MatchData2025(
                season=season.id,
                team_number=3333,
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                al4c=1,
                tl4c=1,
                tNet=1,
                endgame=Endgame2025.SHALLOW,
            ),
            MatchData2025(
                season=season.id,
                team_number=4444,
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                al4c=2,
                tl4c=2,
                tNet=1,
                endgame=Endgame2025.DEEP,
            ),
        ]

        generator = PickListGenerator2025(
            season=season.id,
            organization_id=organization.id,
            title="Total Points Generator",
            notes="",
            favorited=False,
            total_points=1.0,
        )

        session.add(organization_event)
        session.add_all(team_entries)
        session.add_all(match_data)
        session.add(generator)
        await session.commit()
        await session.refresh(generator)

        return user_id, membership.id, generator.id


@pytest.fixture(scope="module")
def prepared_picklist_generation_data(setup_database):
    return asyncio.run(_prepare_picklist_generation_data())


@pytest.fixture
def picklist_client(prepared_picklist_generation_data):
    user_id, membership_id, _ = prepared_picklist_generation_data

    async def override_current_user():
        return {
            "id": str(user_id),
            "displayName": "Picklist User",
            "email": "picklist@example.com",
            "user_org": membership_id,
        }

    app.dependency_overrides[get_current_user] = override_current_user

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.pop(get_current_user, None)


def test_create_picklist_with_generator(
    picklist_client, prepared_picklist_generation_data
):
    _, _, generator_id = prepared_picklist_generation_data

    response = picklist_client.post(
        "/picklists",
        json={"title": "Generated Picklist", "generatorId": str(generator_id)},
    )

    assert response.status_code == 200
    payload = response.json()

    ranks = payload["ranks"]
    assert len(ranks) == 2
    assert ranks[0]["rank"] == 1
    assert ranks[0]["team_number"] == 4444
    assert ranks[1]["team_number"] == 3333
