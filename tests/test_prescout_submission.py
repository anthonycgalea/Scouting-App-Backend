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
    Organization,
    OrganizationEvent,
    Prescout2025,
    Season,
    TeamRecord,
    User,
    UserOrganization,
    UserRole,
)
from tests.conftest import AsyncSessionLocal


async def _prepare_prescout_context():
    async with AsyncSessionLocal() as session:
        season = Season(id=99, year=2025, name="REEFSCAPE")
        event = FRCEvent(
            event_key="2025prescouttest",
            event_name="Prescout Test Event",
            short_name="Prescout",
            year=2025,
            week=5,
        )
        organization = Organization(name="Prescout Org", team_number=51)
        team = TeamRecord(teamNumber=51, teamName="Team 51")
        user_id = uuid4()
        now = datetime.utcnow()
        user = User(
            id=user_id,
            email="prescout@example.com",
            auth_provider="discord",
            display_name="Prescout User",
            logged_in_user_org=None,
            created_at=now,
            updated_at=now,
        )

        session.add_all([season, event, organization, team, user])
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
            "membership_id": membership.id,
            "organization_id": organization.id,
            "team_number": team.team_number,
            "event_key": event.event_key,
            "user_id": user_id,
        }


def test_submit_prescout_record_with_scoring_fields(setup_database):
    context = asyncio.run(_prepare_prescout_context())

    async def override_current_user():
        return {
            "id": str(context["user_id"]),
            "displayName": "Prescout User",
            "email": "prescout@example.com",
            "user_org": context["membership_id"],
        }

    app.dependency_overrides[get_current_user] = override_current_user

    payload = {
        "teamNumber": context["team_number"],
        "matchNumber": 12,
        "matchLevel": "qm",
        "notes": None,
        "al4c": 2,
        "al3c": 1,
        "al2c": 0,
        "al1c": 0,
        "tl4c": 3,
        "tl3c": 2,
        "tl2c": 1,
        "tl1c": 0,
        "aProcessor": 1,
        "tProcessor": 2,
        "aNet": 0,
        "tNet": 1,
        "endgame": Endgame2025.DEEP.value,
    }

    with TestClient(app) as client:
        response = client.post("/scout/prescout", json=payload)

    app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 201
    body = response.json()
    assert body["team_number"] == context["team_number"]
    assert body["event_key"] == context["event_key"]
    assert body["match_number"] == payload["matchNumber"]
    assert body["match_level"] == payload["matchLevel"]

    async def _fetch_prescout():
        async with AsyncSessionLocal() as session:
            statement = select(Prescout2025).where(
                Prescout2025.event_key == context["event_key"],
                Prescout2025.match_number == payload["matchNumber"],
                Prescout2025.match_level == payload["matchLevel"],
                Prescout2025.team_number == context["team_number"],
            )
            result = await session.execute(statement)
            return result.scalars().first()

    stored = asyncio.run(_fetch_prescout())
    assert stored is not None
    assert stored.al4c == payload["al4c"]
    assert stored.tl4c == payload["tl4c"]
    assert stored.aProcessor == payload["aProcessor"]
    assert stored.endgame == Endgame2025.DEEP
