from datetime import datetime
from uuid import uuid4

import pytest
from sqlmodel import select

from app.models import (
    DataValidation,
    Endgame2025,
    FRCEvent,
    MatchData2025,
    MatchSchedule,
    Organization,
    OrganizationEvent,
    Season,
    TeamRecord,
    User,
    UserOrganization,
    UserRole,
    ValidationStatus,
)
from app.services.scout import update_tba_match_data_for_pending_alliances

from tests.conftest import AsyncSessionLocal


class _DummyResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


class _DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        return _DummyResponse(
            {
                "score_breakdown": {
                    "red": {
                        "autoReef": {
                            "tba_topRowCount": 1,
                            "tba_midRowCount": 1,
                            "tba_botRowCount": 1,
                            "trough": 0,
                        },
                        "teleopReef": {
                            "tba_topRowCount": 2,
                            "tba_midRowCount": 2,
                            "tba_botRowCount": 2,
                            "trough": 0,
                        },
                        "netAlgaeCount": 3,
                        "wallAlgaeCount": 3,
                        "endGameRobot1": "DeepCage",
                        "endGameRobot2": "Parked",
                        "endGameRobot3": None,
                    },
                    "blue": {},
                }
            }
        )


@pytest.mark.asyncio
async def test_alliance_validations_marked_valid_when_tba_matches(monkeypatch):
    monkeypatch.setenv("TBA_API_KEY", "test-key")
    monkeypatch.setattr("app.services.scout.httpx.AsyncClient", _DummyAsyncClient)

    async with AsyncSessionLocal() as session:
        season = Season(id=1, year=2025, name="REEFSCAPE")
        event = FRCEvent(
            event_key="2025auto",
            event_name="Auto Validate Event",
            short_name="Auto",
            year=2025,
            week=1,
        )
        organization = Organization(name="Auto Org", team_number=9999)

        user_id = uuid4()
        user = User(
            id=user_id,
            email="auto@example.com",
            auth_provider="discord",
            display_name="Auto User",
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

        match_schedule = MatchSchedule(
            event_key=event.event_key,
            match_number=1,
            match_level="qm",
            red1_id=1111,
            red2_id=2222,
            red3_id=3333,
            blue1_id=4444,
            blue2_id=5555,
            blue3_id=6666,
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
                notes="",
                al4c=1,
                tl4c=2,
                aNet=1,
                tProcessor=1,
                endgame=Endgame2025.DEEP,
            ),
            MatchData2025(
                season=season.id,
                team_number=2222,
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                notes="",
                al3c=1,
                tl3c=2,
                tNet=1,
                aProcessor=1,
                endgame=Endgame2025.PARK,
            ),
            MatchData2025(
                season=season.id,
                team_number=3333,
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                notes="",
                al2c=1,
                tl2c=2,
                tNet=1,
                tProcessor=1,
                endgame=Endgame2025.NONE,
            ),
        ]

        session.add(organization_event)
        session.add(match_schedule)
        session.add_all(match_data)
        await session.commit()

        user_payload = {
            "id": str(user_id),
            "displayName": "Auto User",
            "email": "auto@example.com",
            "user_org": membership.id,
        }

        result = await update_tba_match_data_for_pending_alliances(session, user_payload)

        validation_result = await session.execute(select(DataValidation))
        validations = validation_result.scalars().all()

        assert len(validations) == 3
        assert all(v.validation_status == ValidationStatus.VALID for v in validations)
        assert result["updated_validations"] == 3
