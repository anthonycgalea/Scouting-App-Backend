from datetime import datetime
from uuid import uuid4

import pytest

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
from app.services.match_prediction import calculate_weighted_match_statistics
from tests.conftest import AsyncSessionLocal


@pytest.mark.asyncio
async def test_weighted_statistics_include_calculated_point_fields(setup_database):
    async with AsyncSessionLocal() as session:
        season = Season(id=99, year=2025, name="REEFSCAPE Test")
        event = FRCEvent(
            event_key="2025prediction",
            event_name="Prediction Event",
            short_name="Predict",
            year=2025,
            week=1,
        )
        organization = Organization(name="Prediction Org", team_number=1234)
        now = datetime.utcnow()
        user_id = uuid4()
        user = User(
            id=user_id,
            email="predict@example.com",
            auth_provider="discord",
            display_name="Predict User",
            logged_in_user_org=None,
            created_at=now,
            updated_at=now,
        )
        team_record = TeamRecord(team_number=1234, team_name="Team 1234")

        session.add_all([season, event, organization, user, team_record])
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

        matches = [
            MatchData2025(
                season=season.id,
                team_number=team_record.team_number,
                event_key=event.event_key,
                match_number=2,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                al3c=2,
                aProcessor=1,
                tl2c=1,
                tNet=1,
                endgame=Endgame2025.PARK,
            ),
            MatchData2025(
                season=season.id,
                team_number=team_record.team_number,
                event_key=event.event_key,
                match_number=3,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                al4c=1,
                aNet=1,
                tl3c=2,
                tProcessor=1,
                endgame=Endgame2025.SHALLOW,
            ),
        ]
        session.add_all(matches)
        await session.commit()

        user_payload = {"id": str(user_id), "user_org": membership.id}

        result = await calculate_weighted_match_statistics(session, user_payload)

        assert result["sample_size"] == 2
        statistics = result["statistics"]

        assert "autonomous_points" in statistics
        assert "teleop_points" in statistics
        assert "endgame_points" in statistics

        auto_average = statistics["autonomous_points"]["weighted_average"]
        teleop_average = statistics["teleop_points"]["weighted_average"]
        endgame_average = statistics["endgame_points"]["weighted_average"]

        assert auto_average == pytest.approx(12.5)
        assert teleop_average == pytest.approx(8.5)
        assert endgame_average == pytest.approx(4.0)

        auto_std = statistics["autonomous_points"]["weighted_standard_deviation"]
        teleop_std = statistics["teleop_points"]["weighted_standard_deviation"]
        endgame_std = statistics["endgame_points"]["weighted_standard_deviation"]

        assert auto_std == pytest.approx(1.5)
        assert teleop_std == pytest.approx(1.5)
        assert endgame_std == pytest.approx(2.0)
