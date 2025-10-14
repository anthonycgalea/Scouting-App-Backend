import asyncio
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import select

from app.auth.dependencies import get_current_user
from app.main import app
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


async def _prepare_match_submission_context():
    async with AsyncSessionLocal() as session:
        season = Season(id=42, year=2025, name="REEFSCAPE")
        event = FRCEvent(
            event_key="2025payloadaliases",
            event_name="Payload Alias Test Event",
            short_name="Alias",
            year=2025,
            week=3,
        )
        organization = Organization(name="Alias Org", team_number=51)
        user_id = uuid4()
        now = datetime.utcnow()
        user = User(
            id=user_id,
            email="alias@example.com",
            auth_provider="discord",
            display_name="Alias User",
            logged_in_user_org=None,
            created_at=now,
            updated_at=now,
        )
        team = TeamRecord(teamNumber=51, teamName="Team 51")

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
        session.add(organization_event)
        await session.commit()

        return {
            "season_id": season.id,
            "event_key": event.event_key,
            "organization_id": organization.id,
            "membership_id": membership.id,
            "user_id": user_id,
            "team_number": team.team_number,
        }


def test_submit_match_accepts_camel_case_payload_aliases(setup_database):
    context = asyncio.run(_prepare_match_submission_context())

    async def override_current_user():
        return {
            "id": str(context["user_id"]),
            "displayName": "Alias User",
            "email": "alias@example.com",
            "user_org": context["membership_id"],
        }

    app.dependency_overrides[get_current_user] = override_current_user

    payload = {
        "teamNumber": context["team_number"],
        "matchNumber": 71,
        "matchLevel": "qm",
        "notes": "Arm was broken",
        "endgame": Endgame2025.DEEP.value,
        "eventKey": context["event_key"],
        "aNet": 0,
        "aProcessor": 0,
        "al1c": 0,
        "al2c": 0,
        "al3c": 0,
        "al4c": 0,
        "tNet": 0,
        "tProcessor": 0,
        "tl1c": 0,
        "tl2c": 0,
        "tl3c": 0,
        "tl4c": 0,
    }

    with TestClient(app) as client:
        response = client.post("/scout/submit", json=payload)

    app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    body = response.json()
    assert body["team_number"] == context["team_number"]
    assert body["event_key"] == context["event_key"]
    assert body["match_number"] == payload["matchNumber"]
    assert body["match_level"] == payload["matchLevel"]
    assert body["notes"] == payload["notes"]

    async def _fetch_match():
        async with AsyncSessionLocal() as session:
            statement = select(MatchData2025).where(
                MatchData2025.event_key == context["event_key"],
                MatchData2025.match_number == payload["matchNumber"],
                MatchData2025.match_level == payload["matchLevel"],
                MatchData2025.team_number == context["team_number"],
            )
            result = await session.execute(statement)
            return result.scalars().first()

    stored_match = asyncio.run(_fetch_match())
    assert stored_match is not None
    assert stored_match.notes == payload["notes"]
