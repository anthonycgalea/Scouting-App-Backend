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


def test_get_team_event_detailed_summary(summary_client):
    response = summary_client.get("/analytics/event/teams/detailed")

    assert response.status_code == 200
    payload = response.json()

    assert isinstance(payload, list)
    assert len(payload) == 2

    first, second = payload

    assert first["team_number"] == 1111
    assert first["matches_played"] == 2

    autonomous = first["autonomous_points"]
    assert autonomous["min"] == pytest.approx(6.0)
    assert autonomous["lowerQuartile"] == pytest.approx(8.75)
    assert autonomous["median"] == pytest.approx(11.5)
    assert autonomous["upperQuartile"] == pytest.approx(14.25)
    assert autonomous["max"] == pytest.approx(17.0)
    assert autonomous["average"] == pytest.approx(11.5)

    teleop = first["teleop_points"]
    assert teleop["min"] == pytest.approx(10.0)
    assert teleop["lowerQuartile"] == pytest.approx(11.5)
    assert teleop["median"] == pytest.approx(13.0)
    assert teleop["upperQuartile"] == pytest.approx(14.5)
    assert teleop["max"] == pytest.approx(16.0)
    assert teleop["average"] == pytest.approx(13.0)

    game_pieces = first["game_pieces"]
    assert game_pieces["min"] == pytest.approx(6.0)
    assert game_pieces["lowerQuartile"] == pytest.approx(6.25)
    assert game_pieces["median"] == pytest.approx(6.5)
    assert game_pieces["upperQuartile"] == pytest.approx(6.75)
    assert game_pieces["max"] == pytest.approx(7.0)
    assert game_pieces["average"] == pytest.approx(6.5)

    total_points = first["total_points"]
    assert total_points["min"] == pytest.approx(18.0)
    assert total_points["lowerQuartile"] == pytest.approx(23.25)
    assert total_points["median"] == pytest.approx(28.5)
    assert total_points["upperQuartile"] == pytest.approx(33.75)
    assert total_points["max"] == pytest.approx(39.0)
    assert total_points["average"] == pytest.approx(28.5)

    assert second["team_number"] == 2222
    assert second["matches_played"] == 1

    second_auto = second["autonomous_points"]
    for key in ("min", "lowerQuartile", "median", "upperQuartile", "max", "average"):
        assert second_auto[key] == pytest.approx(16.0)

    second_teleop = second["teleop_points"]
    for key in ("min", "lowerQuartile", "median", "upperQuartile", "max", "average"):
        assert second_teleop[key] == pytest.approx(13.0)

    second_game_pieces = second["game_pieces"]
    for key in ("min", "lowerQuartile", "median", "upperQuartile", "max", "average"):
        assert second_game_pieces[key] == pytest.approx(8.0)

    second_total = second["total_points"]
    for key in ("min", "lowerQuartile", "median", "upperQuartile", "max", "average"):
        assert second_total[key] == pytest.approx(41.0)
