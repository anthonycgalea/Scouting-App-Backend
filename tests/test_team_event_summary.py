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
    Season,
    TeamEvent,
    TeamRecord,
    User,
    UserOrganization,
    UserRole,
)
from tests.conftest import AsyncSessionLocal


async def _prepare_event_summary_data():
    async with AsyncSessionLocal() as session:
        season = Season(id=1, year=2025, name="REEFSCAPE")
        event = FRCEvent(
            event_key="2025summary",
            event_name="Summary Event",
            short_name="Summary",
            year=2025,
            week=2,
        )
        organization = Organization(name="Summary Org", team_number=4321)
        user_id = uuid4()
        user = User(
            id=user_id,
            email="summary@example.com",
            auth_provider="discord",
            display_name="Summary User",
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
        team_entries = [
            TeamEvent(event_key=event.event_key, team_number=1111),
            TeamEvent(event_key=event.event_key, team_number=2222),
        ]

        match_data = [
            MatchData2025(
                season=season.id,
                team_number=1111,
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                al4c=1,
                al3c=1,
                aNet=1,
                tl4c=2,
                tNet=1,
                tProcessor=1,
                endgame=Endgame2025.SHALLOW,
            ),
            MatchData2025(
                season=season.id,
                team_number=1111,
                event_key=event.event_key,
                match_number=2,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                al2c=1,
                aProcessor=1,
                tl3c=1,
                tl1c=2,
                tProcessor=1,
                endgame=Endgame2025.PARK,
            ),
            MatchData2025(
                season=season.id,
                team_number=2222,
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                al3c=2,
                aNet=1,
                tl2c=3,
                tProcessor=2,
                endgame=Endgame2025.DEEP,
            ),
        ]

        session.add(organization_event)
        session.add_all(team_entries)
        session.add_all(match_data)
        await session.commit()

        return user_id, membership.id


@pytest.fixture(scope="module")
def prepared_event_summary_data(setup_database):
    return asyncio.run(_prepare_event_summary_data())


@pytest.fixture
def summary_client(prepared_event_summary_data):
    user_id, membership_id = prepared_event_summary_data

    async def override_current_user():
        return {
            "id": str(user_id),
            "displayName": "Summary User",
            "email": "summary@example.com",
            "user_org": membership_id,
        }

    app.dependency_overrides[get_current_user] = override_current_user

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.pop(get_current_user, None)


def test_get_team_event_summary(summary_client):
    response = summary_client.get("/analytics/eventSummary/teams")

    assert response.status_code == 200
    payload = response.json()

    assert isinstance(payload, list)
    assert len(payload) == 2

    first, second = payload

    assert first["team_number"] == 1111
    assert first["matches_played"] == 2
    assert first["autonomous_points_average"] == pytest.approx(13.5)
    assert first["teleop_points_average"] == pytest.approx(16.0)
    assert first["endgame_points_average"] == pytest.approx(4.0)
    assert first["game_piece_average"] == pytest.approx(6.5)
    assert first["total_points_average"] == pytest.approx(33.5)

    assert second["team_number"] == 2222
    assert second["matches_played"] == 1
    assert second["autonomous_points_average"] == pytest.approx(14.0)
    assert second["teleop_points_average"] == pytest.approx(21.0)
    assert second["endgame_points_average"] == pytest.approx(12.0)
    assert second["game_piece_average"] == pytest.approx(8.0)
    assert second["total_points_average"] == pytest.approx(47.0)
