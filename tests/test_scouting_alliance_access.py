from datetime import datetime
from uuid import uuid4

import pytest

from app.models import (
    FRCEvent,
    MatchData2025,
    MatchPredictions2025,
    MatchSchedule,
    Organization,
    OrganizationEvent,
    OrganizationEventAlliance,
    OrgEventAllianceInviteStatus,
    Season,
    SuperScoutData2025,
    TeamRecord,
    User,
    UserOrganization,
    UserRole,
)
from app.services.match_prediction import get_match_prediction_for_user_organization
from app.services.scout import (
    get_superscout_records,
    get_superscouted_match_alliances,
)
from app.services.team import get_match_data_for_team_at_active_event
from tests.conftest import AsyncSessionLocal


async def _create_alliance_context(event_key: str, season_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        now = datetime.utcnow()

        season = Season(id=season_id, year=2025, name=f"Season {season_id}")
        event = FRCEvent(
            event_key=event_key,
            event_name="Alliance Test Event",
            short_name="Alliance",
            year=2025,
            week=1,
        )
        primary_org = Organization(name=f"Primary {event_key}", team_number=season_id)
        allied_org = Organization(name=f"Allied {event_key}", team_number=season_id + 1)

        primary_user_id = uuid4()
        allied_user_id = uuid4()

        primary_user = User(
            id=primary_user_id,
            email=f"primary-{event_key}@example.com",
            auth_provider="discord",
            display_name="Primary User",
            logged_in_user_org=None,
            created_at=now,
            updated_at=now,
        )
        allied_user = User(
            id=allied_user_id,
            email=f"allied-{event_key}@example.com",
            auth_provider="discord",
            display_name="Allied User",
            logged_in_user_org=None,
            created_at=now,
            updated_at=now,
        )

        session.add_all(
            [season, event, primary_org, allied_org, primary_user, allied_user]
        )
        await session.commit()
        await session.refresh(primary_org)
        await session.refresh(allied_org)

        primary_membership = UserOrganization(
            user_id=primary_user_id,
            organization_id=primary_org.id,
            role=UserRole.MEMBER,
        )
        allied_membership = UserOrganization(
            user_id=allied_user_id,
            organization_id=allied_org.id,
            role=UserRole.MEMBER,
        )
        session.add_all([primary_membership, allied_membership])
        await session.commit()
        await session.refresh(primary_membership)

        primary_event = OrganizationEvent(
            organization_id=primary_org.id,
            event_key=event.event_key,
            public_data=True,
            active=True,
        )
        allied_event = OrganizationEvent(
            organization_id=allied_org.id,
            event_key=event.event_key,
            public_data=True,
            active=True,
        )
        session.add_all([primary_event, allied_event])
        await session.commit()
        await session.refresh(primary_event)

        alliance = OrganizationEventAlliance(
            orgevent_Uid=primary_event.id,
            other_organization_id=allied_org.id,
            org_invite_status=OrgEventAllianceInviteStatus.ACCEPTED,
        )
        session.add(alliance)
        await session.commit()

        return {
            "season_id": season.id,
            "event_key": event.event_key,
            "primary_user_id": primary_user_id,
            "primary_membership_id": primary_membership.id,
            "primary_organization_id": primary_org.id,
            "allied_user_id": allied_user_id,
            "allied_organization_id": allied_org.id,
        }


@pytest.mark.asyncio
async def test_match_data_includes_alliance_records(setup_database):
    context = await _create_alliance_context("2025alliancemd", 9001)

    async with AsyncSessionLocal() as session:
        team = TeamRecord(teamNumber=1234, teamName="Alliance Team")
        session.add(team)
        await session.commit()

        match_entry = MatchData2025(
            season=context["season_id"],
            team_number=team.team_number,
            event_key=context["event_key"],
            match_number=1,
            match_level="qm",
            user_id=context["allied_user_id"],
            organization_id=context["allied_organization_id"],
        )
        session.add(match_entry)
        await session.commit()

        user_payload = {
            "id": str(context["primary_user_id"]),
            "user_org": context["primary_membership_id"],
        }

        records = await get_match_data_for_team_at_active_event(
            session, team.team_number, user_payload
        )

        assert len(records) == 1
        assert records[0].organization_id == context["allied_organization_id"]


@pytest.mark.asyncio
async def test_superscout_access_includes_allied_data(setup_database):
    context = await _create_alliance_context("2025alliancescout", 9002)

    async with AsyncSessionLocal() as session:
        teams = [
            TeamRecord(teamNumber=number, teamName=f"Team {number}")
            for number in range(5001, 5007)
        ]
        session.add_all(teams)
        await session.commit()

        schedule = MatchSchedule(
            event_key=context["event_key"],
            match_number=7,
            match_level="qm",
            red1_id=5001,
            red2_id=5002,
            red3_id=5003,
            blue1_id=5004,
            blue2_id=5005,
            blue3_id=5006,
        )
        session.add(schedule)
        await session.commit()

        superscout_entries = [
            SuperScoutData2025(
                season=context["season_id"],
                team_number=team_number,
                event_key=context["event_key"],
                match_number=7,
                match_level="qm",
                user_id=context["allied_user_id"],
                organization_id=context["allied_organization_id"],
                robot_overall=4,
            )
            for team_number in (5001, 5002, 5003)
        ]
        session.add_all(superscout_entries)
        await session.commit()

        user_payload = {
            "id": str(context["primary_user_id"]),
            "user_org": context["primary_membership_id"],
        }

        records = await get_superscout_records(session, user_payload)
        assert len(records) == 3
        assert {
            record.organization_id for record in records
        } == {context["allied_organization_id"]}

        alliances = await get_superscouted_match_alliances(session, user_payload)
        assert alliances
        alliance_info = alliances[0]["alliances"]
        assert alliance_info["red"] is True
        assert alliance_info["blue"] is False


@pytest.mark.asyncio
async def test_match_prediction_fetches_allied_results(setup_database):
    context = await _create_alliance_context("2025alliancepred", 9003)

    async with AsyncSessionLocal() as session:
        prediction = MatchPredictions2025(
            season=context["season_id"],
            event_key=context["event_key"],
            match_number=15,
            match_level="qm",
            organization_id=context["allied_organization_id"],
            red_alliance_win_pct=0.65,
            blue_alliance_win_pct=0.35,
        )
        session.add(prediction)
        await session.commit()

        user_payload = {
            "id": str(context["primary_user_id"]),
            "user_org": context["primary_membership_id"],
        }

        record = await get_match_prediction_for_user_organization(
            session, user_payload, "qm", 15
        )

        assert record.organization_id == context["allied_organization_id"]
        assert record.red_alliance_win_pct == pytest.approx(0.65)
