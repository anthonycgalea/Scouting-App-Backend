import asyncio
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import app
from app.models import (
    Endgame2025,
    Endgame2026,
    FRCEvent,
    MatchData2025,
    MatchData2026,
    Organization,
    OrganizationEvent,
    Prescout2025,
    Prescout2026,
    Season,
    SuperScoutData2026,
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

        prescout_data = [
            Prescout2025(
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
            Prescout2025(
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
            Prescout2025(
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
        session.add_all(prescout_data)
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
    assert first["autonomous_points_average"] == pytest.approx(11.5)
    assert first["teleop_points_average"] == pytest.approx(13.0)
    assert first["endgame_points_average"] == pytest.approx(4.0)
    assert first["game_piece_average"] == pytest.approx(6.5)
    assert first["total_points_average"] == pytest.approx(28.5)

    assert second["team_number"] == 2222
    assert second["matches_played"] == 1
    assert second["autonomous_points_average"] == pytest.approx(16.0)
    assert second["teleop_points_average"] == pytest.approx(13.0)
    assert second["endgame_points_average"] == pytest.approx(12.0)
    assert second["game_piece_average"] == pytest.approx(8.0)
    assert second["total_points_average"] == pytest.approx(41.0)


def test_get_team_prescout_summary(summary_client):
    response = summary_client.get("/analytics/prescout/teams")

    assert response.status_code == 200
    payload = response.json()

    assert isinstance(payload, list)
    assert len(payload) == 2

    first, second = payload

    assert first["team_number"] == 1111
    assert first["matches_played"] == 2
    assert first["autonomous_points_average"] == pytest.approx(11.5)
    assert first["teleop_points_average"] == pytest.approx(13.0)
    assert first["endgame_points_average"] == pytest.approx(4.0)
    assert first["game_piece_average"] == pytest.approx(6.5)
    assert first["total_points_average"] == pytest.approx(28.5)

    assert second["team_number"] == 2222
    assert second["matches_played"] == 1
    assert second["autonomous_points_average"] == pytest.approx(16.0)
    assert second["teleop_points_average"] == pytest.approx(13.0)
    assert second["endgame_points_average"] == pytest.approx(12.0)
    assert second["game_piece_average"] == pytest.approx(8.0)
    assert second["total_points_average"] == pytest.approx(41.0)


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


def test_get_team_prescout_detailed_summary(summary_client):
    response = summary_client.get("/analytics/prescout/teams/detailed")

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


def test_get_team_event_z_scores(summary_client):
    response = summary_client.get("/analytics/event/teams/zScores")

    assert response.status_code == 200
    payload = response.json()

    teams = payload["teams"]
    assert len(teams) == 2

    first, second = teams
    assert first["team_number"] == 1111
    assert second["team_number"] == 2222

    assert first["autonomous_level_4_coral_average"] == pytest.approx(0.5)
    assert first["teleop_cycles_average"] == pytest.approx(4.0)
    assert second["teleop_cycles_average"] == pytest.approx(5.0)

    assert first["autonomous_level_4_coral_z"] == pytest.approx(1.0)
    assert second["autonomous_level_4_coral_z"] == pytest.approx(-1.0)
    assert first["teleop_cycles_z"] == pytest.approx(-1.0)
    assert second["teleop_cycles_z"] == pytest.approx(1.0)
    assert first["autonomous_level_1_coral_z"] == pytest.approx(0.0)
    assert second["autonomous_level_1_coral_z"] == pytest.approx(0.0)

    game_specific_2026_fields = {
        "autonomous_fuel_average",
        "teleop_fuel_average",
        "total_fuel_average",
        "autonomous_passing_average",
        "teleop_passing_average",
        "autonomous_climb_average",
        "superscout_overall_score_average",
        "superscout_driver_score_average",
        "superscout_defense_score_average",
    }
    assert game_specific_2026_fields.isdisjoint(first.keys())
    assert game_specific_2026_fields.isdisjoint(second.keys())

    extremes = payload["z_score_extremes"]
    assert extremes["autonomous_level_4_coral_average"]["min"] == pytest.approx(-1.0)
    assert extremes["autonomous_level_4_coral_average"]["max"] == pytest.approx(1.0)
    assert extremes["teleop_cycles_average"]["min"] == pytest.approx(-1.0)
    assert extremes["teleop_cycles_average"]["max"] == pytest.approx(1.0)


def _assert_head_to_head_statistic(statistic, expected):
    for key, value in expected.items():
        assert statistic[key] == pytest.approx(value)


def test_get_team_event_head_to_head(summary_client):
    response = summary_client.get("/analytics/event/teams/headToHead")

    assert response.status_code == 200
    payload = response.json()

    assert isinstance(payload, list)
    assert len(payload) == 2

    first, second = payload

    assert first["team_number"] == 1111
    assert first["matches_played"] == 2
    assert first["endgame_success_rate"] == pytest.approx(50.0)

    _assert_head_to_head_statistic(
        first["autonomous_coral"],
        {"min": 1.0, "max": 2.0, "median": 1.5, "average": 1.5, "stdev": 0.5},
    )
    _assert_head_to_head_statistic(
        first["autonomous_net_algae"],
        {"min": 0.0, "max": 1.0, "median": 0.5, "average": 0.5, "stdev": 0.5},
    )
    _assert_head_to_head_statistic(
        first["autonomous_processor_algae"],
        {"min": 0.0, "max": 1.0, "median": 0.5, "average": 0.5, "stdev": 0.5},
    )
    _assert_head_to_head_statistic(
        first["autonomous_points"],
        {"min": 6.0, "max": 17.0, "median": 11.5, "average": 11.5, "stdev": 5.5},
    )
    _assert_head_to_head_statistic(
        first["teleop_coral"],
        {"min": 2.0, "max": 3.0, "median": 2.5, "average": 2.5, "stdev": 0.5},
    )
    _assert_head_to_head_statistic(
        first["teleop_game_pieces"],
        {"min": 4.0, "max": 4.0, "median": 4.0, "average": 4.0, "stdev": 0.0},
    )
    _assert_head_to_head_statistic(
        first["teleop_points"],
        {"min": 10.0, "max": 16.0, "median": 13.0, "average": 13.0, "stdev": 3.0},
    )
    _assert_head_to_head_statistic(
        first["teleop_net_algae"],
        {"min": 0.0, "max": 1.0, "median": 0.5, "average": 0.5, "stdev": 0.5},
    )
    _assert_head_to_head_statistic(
        first["teleop_processor_algae"],
        {"min": 1.0, "max": 1.0, "median": 1.0, "average": 1.0, "stdev": 0.0},
    )
    _assert_head_to_head_statistic(
        first["endgame_points"],
        {"min": 2.0, "max": 6.0, "median": 4.0, "average": 4.0, "stdev": 2.0},
    )
    _assert_head_to_head_statistic(
        first["total_points"],
        {"min": 18.0, "max": 39.0, "median": 28.5, "average": 28.5, "stdev": 10.5},
    )
    _assert_head_to_head_statistic(
        first["total_net_algae"],
        {"min": 0.0, "max": 2.0, "median": 1.0, "average": 1.0, "stdev": 1.0},
    )

    assert second["team_number"] == 2222
    assert second["matches_played"] == 1
    assert second["endgame_success_rate"] == pytest.approx(100.0)

    for key in (
        "autonomous_coral",
        "autonomous_net_algae",
        "autonomous_processor_algae",
        "autonomous_points",
        "teleop_coral",
        "teleop_game_pieces",
        "teleop_points",
        "teleop_net_algae",
        "teleop_processor_algae",
        "endgame_points",
        "total_points",
        "total_net_algae",
    ):
        stat = second[key]
        expected_value = {
            "autonomous_coral": 2.0,
            "autonomous_net_algae": 1.0,
            "autonomous_processor_algae": 0.0,
            "autonomous_points": 16.0,
            "teleop_coral": 3.0,
            "teleop_game_pieces": 5.0,
            "teleop_points": 13.0,
            "teleop_net_algae": 0.0,
            "teleop_processor_algae": 2.0,
            "endgame_points": 12.0,
            "total_points": 41.0,
            "total_net_algae": 1.0,
        }[key]

        for field in ("min", "max", "median", "average", "stdev"):
            assert stat[field] == pytest.approx(expected_value if field != "stdev" else 0.0)


async def _prepare_event_summary_data_2026():
    async with AsyncSessionLocal() as session:
        season = Season(id=2, year=2026, name="FIRST AGE")
        event = FRCEvent(
            event_key="2026summary",
            event_name="Summary Event 2026",
            short_name="Summary26",
            year=2026,
            week=2,
        )
        organization = Organization(name="Summary Org 2026", team_number=9876)
        user_id = uuid4()
        user = User(
            id=user_id,
            email="summary26@example.com",
            auth_provider="discord",
            display_name="Summary User 2026",
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
            role=UserRole.MEMBER,
        )
        session.add(membership)
        await session.commit()
        await session.refresh(membership)

        session.add(
            OrganizationEvent(
                organization_id=organization.id,
                event_key=event.event_key,
                public_data=True,
                active=True,
            )
        )
        session.add_all(
            [
                TeamEvent(event_key=event.event_key, team_number=3333),
                TeamEvent(event_key=event.event_key, team_number=4444),
            ]
        )

        session.add_all(
            [
                MatchData2026(
                    season=season.id,
                    team_number=3333,
                    event_key=event.event_key,
                    match_number=1,
                    match_level="qm",
                    user_id=user_id,
                    organization_id=organization.id,
                    autoFuel=5,
                    autoPass=4,
                    autoClimb=1,
                    teleopFuel=20,
                    teleopPass=6,
                    endgame=Endgame2026.L1,
                ),
                MatchData2026(
                    season=season.id,
                    team_number=4444,
                    event_key=event.event_key,
                    match_number=1,
                    match_level="qm",
                    user_id=user_id,
                    organization_id=organization.id,
                    autoFuel=8,
                    autoPass=2,
                    autoClimb=0,
                    teleopFuel=12,
                    teleopPass=3,
                    endgame=Endgame2026.L2,
                ),
            ]
        )
        session.add_all(
            [
                Prescout2026(
                    season=season.id,
                    team_number=3333,
                    event_key=event.event_key,
                    match_number=1,
                    match_level="qm",
                    user_id=user_id,
                    organization_id=organization.id,
                    autoFuel=6,
                    autoPass=3,
                    autoClimb=1,
                    teleopFuel=19,
                    teleopPass=7,
                    endgame=Endgame2026.L1,
                ),
                Prescout2026(
                    season=season.id,
                    team_number=4444,
                    event_key=event.event_key,
                    match_number=1,
                    match_level="qm",
                    user_id=user_id,
                    organization_id=organization.id,
                    autoFuel=7,
                    autoPass=1,
                    autoClimb=0,
                    teleopFuel=13,
                    teleopPass=2,
                    endgame=Endgame2026.L2,
                ),
            ]
        )

        session.add_all(
            [
                SuperScoutData2026(
                    season=season.id,
                    team_number=3333,
                    event_key=event.event_key,
                    match_number=1,
                    match_level="qm",
                    user_id=user_id,
                    organization_id=organization.id,
                    robot_overall=3,
                    driver_rating=5,
                    played_defense=False,
                    defense_rating=None,
                ),
                SuperScoutData2026(
                    season=season.id,
                    team_number=4444,
                    event_key=event.event_key,
                    match_number=1,
                    match_level="qm",
                    user_id=user_id,
                    organization_id=organization.id,
                    robot_overall=2,
                    driver_rating=3,
                    played_defense=True,
                    defense_rating=4,
                ),
            ]
        )
        await session.commit()

        return user_id, membership.id


@pytest.fixture(scope="module")
def prepared_event_summary_data_2026(setup_database):
    return asyncio.run(_prepare_event_summary_data_2026())


@pytest.fixture
def summary_client_2026(prepared_event_summary_data_2026):
    user_id, membership_id = prepared_event_summary_data_2026

    async def override_current_user():
        return {
            "id": str(user_id),
            "displayName": "Summary User 2026",
            "email": "summary26@example.com",
            "user_org": membership_id,
        }

    app.dependency_overrides[get_current_user] = override_current_user

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.pop(get_current_user, None)


def test_get_team_event_z_scores_2026_season_2(summary_client_2026):
    response = summary_client_2026.get("/analytics/event/teams/zScores")

    assert response.status_code == 200
    payload = response.json()
    teams = payload["teams"]
    assert len(teams) == 2

    first, second = teams
    assert first["team_number"] == 3333
    assert second["team_number"] == 4444

    assert first["autonomous_fuel_average"] == pytest.approx(5.0)
    assert first["teleop_fuel_average"] == pytest.approx(20.0)
    assert first["total_fuel_average"] == pytest.approx(25.0)
    assert first["autonomous_passing_average"] == pytest.approx(4.0)
    assert first["teleop_passing_average"] == pytest.approx(6.0)
    assert first["autonomous_climb_average"] == pytest.approx(1.0)
    assert first["superscout_overall_score_average"] == pytest.approx(3.0)
    assert first["superscout_driver_score_average"] == pytest.approx(5.0)
    assert first["superscout_defense_score_average"] == pytest.approx(0.0)

    assert second["superscout_defense_score_average"] == pytest.approx(4.0)

    game_specific_2025_fields = {
        "autonomous_level_4_coral_average",
        "autonomous_level_3_coral_average",
        "autonomous_level_2_coral_average",
        "autonomous_level_1_coral_average",
        "teleop_level_4_coral_average",
        "teleop_level_3_coral_average",
        "teleop_level_2_coral_average",
        "teleop_level_1_coral_average",
        "autonomous_net_average",
        "teleop_net_average",
        "autonomous_processor_average",
        "teleop_processor_average",
        "teleop_cycles_average",
        "autonomous_coral_average",
        "autonomous_algae_average",
        "teleop_coral_average",
        "teleop_algae_average",
        "total_coral_average",
        "total_algae_average",
        "total_game_pieces_average",
    }
    assert game_specific_2025_fields.isdisjoint(first.keys())
    assert game_specific_2025_fields.isdisjoint(second.keys())

    extremes = payload["z_score_extremes"]
    assert "autonomous_fuel_average" in extremes
    assert "superscout_overall_score_average" in extremes


def test_get_team_prescout_summary_2026(summary_client_2026):
    response = summary_client_2026.get("/analytics/prescout/teams")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 2

    first, second = payload
    assert first["team_number"] == 3333
    assert second["team_number"] == 4444

    assert first["matches_played"] == 1
    assert first["autonomous_points_average"] == pytest.approx(21.0)
    assert first["teleop_points_average"] == pytest.approx(19.0)
    assert first["endgame_points_average"] == pytest.approx(10.0)
    assert first["game_piece_average"] == pytest.approx(25.0)
    assert first["total_points_average"] == pytest.approx(50.0)

    assert second["matches_played"] == 1
    assert second["autonomous_points_average"] == pytest.approx(7.0)
    assert second["teleop_points_average"] == pytest.approx(13.0)
    assert second["endgame_points_average"] == pytest.approx(20.0)
    assert second["game_piece_average"] == pytest.approx(20.0)
    assert second["total_points_average"] == pytest.approx(40.0)


def test_get_team_event_match_history_2026_fields(summary_client_2026):
    response = summary_client_2026.get("/analytics/event/teams/matches")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2

    first, second = payload
    assert first["team_number"] == 3333
    assert second["team_number"] == 4444

    first_match = first["matches"][0]
    assert first_match["autonomous_fuel_scored"] == pytest.approx(5.0)
    assert first_match["total_fuel"] == pytest.approx(25.0)
    assert first_match["autonomous_climbed"] == pytest.approx(1.0)
    assert first_match["teleop_fuel"] == pytest.approx(20.0)
    assert first_match["teleop_passing"] == pytest.approx(6.0)
    assert first_match["endgame_points"] == pytest.approx(10.0)
    assert first_match["superscout_overall"] == pytest.approx(3.0)
    assert first_match["superscout_driver"] == pytest.approx(5.0)
    assert first_match["superscout_defense"] is None

    second_match = second["matches"][0]
    assert second_match["superscout_defense"] == pytest.approx(4.0)


def test_get_team_event_head_to_head_2026_fields(summary_client_2026):
    response = summary_client_2026.get("/analytics/event/teams/headToHead")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2

    first, second = payload
    assert first["team_number"] == 3333
    assert second["team_number"] == 4444

    _assert_head_to_head_statistic(
        first["autonomous_fuel_scored"],
        {"min": 5.0, "max": 5.0, "median": 5.0, "average": 5.0, "stdev": 0.0},
    )
    _assert_head_to_head_statistic(
        first["autonomous_fuel_passed"],
        {"min": 4.0, "max": 4.0, "median": 4.0, "average": 4.0, "stdev": 0.0},
    )
    _assert_head_to_head_statistic(
        first["autonomous_auto_climb"],
        {"min": 1.0, "max": 1.0, "median": 1.0, "average": 1.0, "stdev": 0.0},
    )
    _assert_head_to_head_statistic(
        first["autonomous_points"],
        {"min": 20.0, "max": 20.0, "median": 20.0, "average": 20.0, "stdev": 0.0},
    )

    _assert_head_to_head_statistic(
        first["teleop_fuel_scored"],
        {"min": 20.0, "max": 20.0, "median": 20.0, "average": 20.0, "stdev": 0.0},
    )
    _assert_head_to_head_statistic(
        first["teleop_fuel_passed"],
        {"min": 6.0, "max": 6.0, "median": 6.0, "average": 6.0, "stdev": 0.0},
    )

    _assert_head_to_head_statistic(
        first["endgame_climb"],
        {"min": 10.0, "max": 10.0, "median": 10.0, "average": 10.0, "stdev": 0.0},
    )
    assert first["endgame_success_rate"] == pytest.approx(100.0)

    _assert_head_to_head_statistic(
        first["total_points"],
        {"min": 50.0, "max": 50.0, "median": 50.0, "average": 50.0, "stdev": 0.0},
    )

    _assert_head_to_head_statistic(
        second["autonomous_points"],
        {"min": 8.0, "max": 8.0, "median": 8.0, "average": 8.0, "stdev": 0.0},
    )
    _assert_head_to_head_statistic(
        second["teleop_fuel_scored"],
        {"min": 12.0, "max": 12.0, "median": 12.0, "average": 12.0, "stdev": 0.0},
    )
    _assert_head_to_head_statistic(
        second["endgame_climb"],
        {"min": 20.0, "max": 20.0, "median": 20.0, "average": 20.0, "stdev": 0.0},
    )
    assert second["endgame_success_rate"] == pytest.approx(100.0)
    _assert_head_to_head_statistic(
        second["total_points"],
        {"min": 40.0, "max": 40.0, "median": 40.0, "average": 40.0, "stdev": 0.0},
    )

    game_specific_2025_fields = {
        "autonomous_coral",
        "autonomous_net_algae",
        "autonomous_processor_algae",
        "teleop_coral",
        "teleop_game_pieces",
        "teleop_net_algae",
        "teleop_processor_algae",
        "total_net_algae",
    }
    assert game_specific_2025_fields.isdisjoint(first.keys())
    assert game_specific_2025_fields.isdisjoint(second.keys())
