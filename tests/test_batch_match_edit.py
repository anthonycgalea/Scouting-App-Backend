import asyncio
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlmodel import select

import sys

APP_PATH = Path(__file__).resolve().parents[1] / "app"
if str(APP_PATH) not in sys.path:
    sys.path.append(str(APP_PATH))

from models import (  # type: ignore[import]
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
    PredictionQueue,
)
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

from app.services.scout import batch_update_match
from tests.conftest import AsyncSessionLocal


async def _prepare_batch_edit_context():
    async with AsyncSessionLocal() as session:
        season = Season(id=7301, year=2025, name="Batch Edit Season")
        event = FRCEvent(
            event_key="2025batchedit",
            event_name="Batch Edit Event",
            short_name="Batch Edit",
            year=2025,
            week=2,
        )
        organization = Organization(name="Batch Edit Org", team_number=7301)
        user_id = uuid4()
        now = datetime.utcnow()
        user = User(
            id=user_id,
            email="batchedit@example.com",
            auth_provider="discord",
            display_name="Batch Editor",
            logged_in_user_org=None,
            created_at=now,
            updated_at=now,
        )
        team = TeamRecord(teamNumber=7301, teamName="Batch Edit Team")

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

def test_batch_update_match_commits_changes(setup_database):
    context = asyncio.run(_prepare_batch_edit_context())

    async def _perform_update():
        async with AsyncSessionLocal() as session:
            original_match = MatchData2025(
                season=context["season_id"],
                team_number=context["team_number"],
                event_key=context["event_key"],
                match_number=1,
                match_level="qm",
                user_id=context["user_id"],
                organization_id=context["organization_id"],
                endgame=Endgame2025.PARK,
            )
            session.add(original_match)
            await session.commit()

            schedule_kwargs = dict(
                event_key=context["event_key"],
                match_level="qm",
                red1_id=context["team_number"],
                red2_id=context["team_number"],
                red3_id=context["team_number"],
                blue1_id=context["team_number"],
                blue2_id=context["team_number"],
                blue3_id=context["team_number"],
            )

            schedule_match_1 = MatchSchedule(
                match_number=1,
                **schedule_kwargs,
            )
            schedule_match_2 = MatchSchedule(
                match_number=2,
                **schedule_kwargs,
            )
            session.add_all([schedule_match_1, schedule_match_2])
            await session.commit()

            updated_match = MatchData2025(
                season=context["season_id"],
                team_number=context["team_number"],
                event_key=context["event_key"],
                match_number=1,
                match_level="qm",
                user_id=context["user_id"],
                organization_id=context["organization_id"],
                endgame=Endgame2025.DEEP,
            )

            user_payload = {
                "id": str(context["user_id"]),
                "user_org": context["membership_id"],
            }

            await batch_update_match(session, [updated_match], user_payload)

    asyncio.run(_perform_update())

    async def _fetch_updated_match():
        async with AsyncSessionLocal() as verification_session:
            statement = select(MatchData2025).where(
                MatchData2025.event_key == context["event_key"],
                MatchData2025.match_number == 1,
                MatchData2025.match_level == "qm",
                MatchData2025.team_number == context["team_number"],
                MatchData2025.user_id == context["user_id"],
            )

            result = await verification_session.execute(statement)
            return result.scalars().first()

    stored_match = asyncio.run(_fetch_updated_match())

    assert stored_match is not None
    assert stored_match.endgame == Endgame2025.DEEP

    async def _fetch_prediction_queue():
        async with AsyncSessionLocal() as verification_session:
            statement = select(PredictionQueue).where(
                PredictionQueue.event_key == context["event_key"],
                PredictionQueue.organization_id == context["organization_id"],
            )
            result = await verification_session.execute(statement)
            return result.scalars().all()

    queued_matches = asyncio.run(_fetch_prediction_queue())

    assert len(queued_matches) == 1
    queued_match = queued_matches[0]
    assert queued_match.match_number == 2
    assert queued_match.match_level == "qm"
