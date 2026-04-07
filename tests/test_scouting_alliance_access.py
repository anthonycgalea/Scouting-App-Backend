from datetime import datetime
from uuid import uuid4

import pytest
from sqlmodel import select

from app.models import (
    DataValidation,
    Endgame2025,
    FRCEvent,
    MatchData2025,
    MatchData2026,
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
    ValidationStatus,
)
from app.services.event import get_match_preview, get_scouting_alliance_organization_ids
from app.services.match_prediction import get_match_prediction_for_user_organization
from app.services.scout import (
    DataValidationFilterRequest,
    DataValidationUpdateRequest,
    batch_update_data_validations,
    get_data_validations_for_active_event,
    get_superscout_records,
    get_superscouted_match_alliances,
    update_match_data_and_mark_validation_valid,
)
from app.services.team import get_match_data_for_team_at_active_event
from tests.conftest import AsyncSessionLocal


async def _create_alliance_context(
    event_key: str,
    season_id: int,
    event_year: int = 2025,
    *,
    alliance_from_primary: bool = True,
    invite_status: OrgEventAllianceInviteStatus = OrgEventAllianceInviteStatus.ACCEPTED,
) -> dict:
    async with AsyncSessionLocal() as session:
        now = datetime.utcnow()

        season = Season(id=season_id, year=event_year, name=f"Season {season_id}")
        event = FRCEvent(
            event_key=event_key,
            event_name="Alliance Test Event",
            short_name="Alliance",
            year=event_year,
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
            orgevent_Uid=(
                primary_event.id if alliance_from_primary else allied_event.id
            ),
            other_organization_id=(
                allied_org.id if alliance_from_primary else primary_org.id
            ),
            org_invite_status=invite_status,
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
async def test_match_preview_includes_allied_compiled_averages(setup_database):
    context = await _create_alliance_context("2025alliancepreview", 9302)

    async with AsyncSessionLocal() as session:
        teams = [
            TeamRecord(teamNumber=number, teamName=f"Team {number}")
            for number in range(6101, 6107)
        ]
        session.add_all(teams)
        await session.commit()

        schedule = MatchSchedule(
            event_key=context["event_key"],
            match_number=3,
            match_level="qm",
            red1_id=6101,
            red2_id=6102,
            red3_id=6103,
            blue1_id=6104,
            blue2_id=6105,
            blue3_id=6106,
        )

        allied_record = MatchData2025(
            season=context["season_id"],
            team_number=6101,
            event_key=context["event_key"],
            match_number=1,
            match_level="qm",
            user_id=context["allied_user_id"],
            organization_id=context["allied_organization_id"],
            autoL4=2,
        )
        session.add_all([schedule, allied_record])
        await session.commit()

        user_payload = {
            "id": str(context["primary_user_id"]),
            "user_org": context["primary_membership_id"],
        }

        preview = await get_match_preview(session, user_payload, 3, "qm")
        red_team_preview = next(team for team in preview.red.teams if team.team_number == 6101)
        assert red_team_preview.auto.level4.average == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_data_validation_pull_includes_allied_records(setup_database):
    context = await _create_alliance_context("2025alliancedv", 9100)

    async with AsyncSessionLocal() as session:
        team = TeamRecord(teamNumber=6100, teamName="Alliance DV Team")
        session.add(team)
        await session.commit()

        match_entry = MatchData2025(
            season=context["season_id"],
            team_number=team.team_number,
            event_key=context["event_key"],
            match_number=3,
            match_level="qm",
            user_id=context["allied_user_id"],
            organization_id=context["allied_organization_id"],
        )
        validation_record = DataValidation(
            event_key=context["event_key"],
            match_number=3,
            match_level="qm",
            user_id=context["allied_user_id"],
            team_number=team.team_number,
            organization_id=context["allied_organization_id"],
        )

        session.add_all([match_entry, validation_record])
        await session.commit()

        user_payload = {
            "id": str(context["primary_user_id"]),
            "user_org": context["primary_membership_id"],
        }

        filters = DataValidationFilterRequest(teamNumber=team.team_number)
        records = await get_data_validations_for_active_event(
            session, user_payload, filters
        )

        assert len(records) == 1
        assert records[0].organization_id == context["allied_organization_id"]


@pytest.mark.asyncio
async def test_data_validation_pull_includes_incoming_allied_records(setup_database):
    context = await _create_alliance_context(
        "2025alliancedvincoming", 9101, alliance_from_primary=False
    )

    async with AsyncSessionLocal() as session:
        team = TeamRecord(teamNumber=6200, teamName="Incoming DV Team")
        session.add(team)
        await session.commit()

        match_entry = MatchData2025(
            season=context["season_id"],
            team_number=team.team_number,
            event_key=context["event_key"],
            match_number=4,
            match_level="qm",
            user_id=context["allied_user_id"],
            organization_id=context["allied_organization_id"],
        )
        validation_record = DataValidation(
            event_key=context["event_key"],
            match_number=4,
            match_level="qm",
            user_id=context["allied_user_id"],
            team_number=team.team_number,
            organization_id=context["allied_organization_id"],
        )

        session.add_all([match_entry, validation_record])
        await session.commit()

        user_payload = {
            "id": str(context["primary_user_id"]),
            "user_org": context["primary_membership_id"],
        }

        records = await get_data_validations_for_active_event(session, user_payload)

        assert len(records) == 1
        assert records[0].organization_id == context["allied_organization_id"]


@pytest.mark.asyncio
async def test_allied_user_can_update_data_validation(setup_database):
    context = await _create_alliance_context("2025alliancedvupdate", 9102)

    async with AsyncSessionLocal() as session:
        team = TeamRecord(teamNumber=6300, teamName="Alliance Update Team")
        session.add(team)
        await session.commit()

        match_entry = MatchData2025(
            season=context["season_id"],
            team_number=team.team_number,
            event_key=context["event_key"],
            match_number=5,
            match_level="qm",
            user_id=context["allied_user_id"],
            organization_id=context["allied_organization_id"],
            al4c=1,
            tl4c=1,
            aNet=0,
            tProcessor=0,
            endgame=Endgame2025.NONE,
        )
        validation_record = DataValidation(
            event_key=context["event_key"],
            match_number=5,
            match_level="qm",
            user_id=context["allied_user_id"],
            team_number=team.team_number,
            organization_id=context["allied_organization_id"],
            validation_status=ValidationStatus.PENDING,
        )

        session.add_all([match_entry, validation_record])
        await session.commit()

        user_payload = {
            "id": str(context["primary_user_id"]),
            "user_org": context["primary_membership_id"],
        }

        update_request = DataValidationUpdateRequest(
            matchNumber=5,
            matchLevel="qm",
            teamNumber=team.team_number,
            userId=context["allied_user_id"],
            validationStatus=ValidationStatus.NEEDS_REVIEW,
            notes="Alliance review",
        )

        updated_records = await batch_update_data_validations(
            session, user_payload, [update_request]
        )

        assert len(updated_records) == 1
        updated_record = updated_records[0]
        assert updated_record.organization_id == context["allied_organization_id"]
        assert updated_record.validation_status == ValidationStatus.NEEDS_REVIEW
        assert updated_record.notes == "Alliance review"

        validation_stmt = select(DataValidation).where(
            DataValidation.event_key == context["event_key"],
            DataValidation.match_number == 5,
            DataValidation.match_level == "qm",
            DataValidation.team_number == team.team_number,
            DataValidation.user_id == context["allied_user_id"],
        )
        validation_result = await session.execute(validation_stmt)
        stored_validation = validation_result.scalars().first()

        assert stored_validation is not None
        assert stored_validation.validation_status == ValidationStatus.NEEDS_REVIEW
        assert stored_validation.notes == "Alliance review"


@pytest.mark.asyncio
async def test_allied_user_can_update_match_data(setup_database):
    context = await _create_alliance_context("2025alliancematchupdate", 9103)

    async with AsyncSessionLocal() as session:
        team = TeamRecord(teamNumber=6400, teamName="Alliance Match Team")
        session.add(team)
        await session.commit()

        match_entry = MatchData2025(
            season=context["season_id"],
            team_number=team.team_number,
            event_key=context["event_key"],
            match_number=6,
            match_level="qm",
            user_id=context["allied_user_id"],
            organization_id=context["allied_organization_id"],
            notes="Original alliance notes",
            al4c=2,
            tl4c=1,
            aNet=1,
            tProcessor=0,
            endgame=Endgame2025.PARK,
        )
        validation_record = DataValidation(
            event_key=context["event_key"],
            match_number=6,
            match_level="qm",
            user_id=context["allied_user_id"],
            team_number=team.team_number,
            organization_id=context["allied_organization_id"],
            validation_status=ValidationStatus.PENDING,
            notes="",
        )

        session.add_all([match_entry, validation_record])
        await session.commit()

        user_payload = {
            "id": str(context["primary_user_id"]),
            "user_org": context["primary_membership_id"],
        }

        updated_match = MatchData2025(
            season=context["season_id"],
            team_number=team.team_number,
            event_key=context["event_key"],
            match_number=6,
            match_level="qm",
            user_id=context["allied_user_id"],
            organization_id=context["allied_organization_id"],
            notes="Alliance correction",
            al4c=3,
            tl4c=2,
            aNet=1,
            tProcessor=1,
            endgame=Endgame2025.DEEP,
        )

        validation = await update_match_data_and_mark_validation_valid(
            session, user_payload, updated_match
        )

        assert validation.organization_id == context["allied_organization_id"]
        assert validation.validation_status == ValidationStatus.VALID
        assert validation.notes == "Alliance correction"

        match_stmt = select(MatchData2025).where(
            MatchData2025.event_key == context["event_key"],
            MatchData2025.match_number == 6,
            MatchData2025.match_level == "qm",
            MatchData2025.team_number == team.team_number,
            MatchData2025.user_id == context["allied_user_id"],
        )
        match_result = await session.execute(match_stmt)
        stored_match = match_result.scalars().first()

        assert stored_match is not None
        assert stored_match.al4c == 3
        assert stored_match.tl4c == 2
        assert stored_match.tProcessor == 1
        assert stored_match.endgame == Endgame2025.DEEP
        assert stored_match.notes == "Original alliance notes"


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


@pytest.mark.asyncio
async def test_removed_alliance_not_accessible(setup_database):
    context = await _create_alliance_context(
        "2025alliancedcl",
        9005,
        invite_status=OrgEventAllianceInviteStatus.PENDING,
    )

    async with AsyncSessionLocal() as session:
        primary_event = (
            await session.exec(
                select(OrganizationEvent).where(
                    OrganizationEvent.organization_id
                    == context["primary_organization_id"],
                    OrganizationEvent.event_key == context["event_key"],
                )
            )
        ).one()

        alliance = (
            await session.exec(
                select(OrganizationEventAlliance).where(
                    OrganizationEventAlliance.orgevent_Uid == primary_event.id,
                    OrganizationEventAlliance.other_organization_id
                    == context["allied_organization_id"],
                )
            )
        ).one()

        await session.delete(alliance)
        await session.commit()

    async with AsyncSessionLocal() as session:
        accessible = await get_scouting_alliance_organization_ids(
            session,
            context["event_key"],
            context["primary_organization_id"],
        )

    assert accessible == {context["primary_organization_id"]}


@pytest.mark.asyncio
async def test_match_data_includes_alliance_records_for_2026(setup_database):
    context = await _create_alliance_context("2026alliancemd", 9301, event_year=2026)

    async with AsyncSessionLocal() as session:
        team = TeamRecord(teamNumber=2234, teamName="Alliance Team 2026")
        session.add(team)
        await session.commit()

        match_entry = MatchData2026(
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
