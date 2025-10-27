from datetime import datetime
import asyncio
import importlib
import os
import sys
from uuid import uuid4

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.modules.setdefault("auth", importlib.import_module("app.auth"))
sys.modules.setdefault("db", importlib.import_module("app.db"))
_models_module = importlib.import_module("app.models")
sys.modules.setdefault("models", _models_module)
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.models."):
        sys.modules.setdefault(_name.replace("app.", "", 1), _module)
_services_module = importlib.import_module("app.services")
sys.modules.setdefault("services", _services_module)
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.services."):
        sys.modules.setdefault(_name.replace("app.", "", 1), _module)
_routes_module = importlib.import_module("app.routes")
sys.modules.setdefault("routes", _routes_module)
for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.routes."):
        sys.modules.setdefault(_name.replace("app.", "", 1), _module)

import pytest
from sqlmodel import select

from models import (
    FRCEvent,
    MatchData2025,
    MatchSchedule,
    Organization,
    OrganizationEvent,
    OrganizationEventAlliance,
    PredictionQueue,
    Season,
    TeamRecord,
    User,
    UserOrganization,
    UserRole,
)
from models.other_organization_event_access import OrgEventAllianceInviteStatus

organizationadmin_module = importlib.import_module("app.routes.organizationadmin")
_enqueue_matches_for_prediction_queue = (
    organizationadmin_module._enqueue_matches_for_prediction_queue
)
from app.services.scout import batch_update_match, edit_2025_match
from tests.conftest import AsyncSessionLocal


def test_enqueue_matches_for_prediction_queue_adds_new_matches(setup_database):
    async def _run_test() -> None:
        async with AsyncSessionLocal() as session:
            event = FRCEvent(event_key="2025queue", event_name="Queue Event", year=2025, week=1)
            organization = Organization(name="Queue Org", team_number=1234)
            session.add_all([event, organization])
            await session.commit()

            await _enqueue_matches_for_prediction_queue(
                session,
                event_key=event.event_key,
                organization_id=organization.id,
                matches=[(1, "qm"), (2, "qm")],
            )
            await session.commit()

            result = await session.execute(
                select(PredictionQueue).where(
                    PredictionQueue.event_key == event.event_key,
                    PredictionQueue.organization_id == organization.id,
                )
            )
            queued_matches = {
                (row.match_number, row.match_level)
                for row in result.scalars().all()
            }
            assert queued_matches == {(1, "qm"), (2, "qm")}

            await _enqueue_matches_for_prediction_queue(
                session,
                event_key=event.event_key,
                organization_id=organization.id,
                matches=[(2, "qm"), (3, "qm")],
            )
            await session.commit()

            result = await session.execute(
                select(PredictionQueue).where(
                    PredictionQueue.event_key == event.event_key,
                    PredictionQueue.organization_id == organization.id,
                )
            )
            queued_matches = {
                (row.match_number, row.match_level)
                for row in result.scalars().all()
            }
            assert queued_matches == {(1, "qm"), (2, "qm"), (3, "qm")}

    asyncio.run(_run_test())


def test_edit_match_enqueues_unplayed_matches(setup_database):
    async def _run_test() -> None:
        async with AsyncSessionLocal() as session:
            season = Season(id=9401, year=2025, name="Queue Season")
            event = FRCEvent(
                event_key="2025editqueue",
                event_name="Queue Edit Event",
                short_name="Queue Edit",
                year=2025,
                week=1,
            )
            organization = Organization(name="Queue Org", team_number=4321)
            user_id = uuid4()
            now = datetime.utcnow()
            user = User(
                id=user_id,
                email="queue@example.com",
                auth_provider="discord",
                display_name="Queue User",
                logged_in_user_org=None,
                created_at=now,
                updated_at=now,
            )
            team_records = [
                TeamRecord(teamNumber=4321, teamName="Queue Team"),
                TeamRecord(teamNumber=1111, teamName="Allied Team 1"),
                TeamRecord(teamNumber=2222, teamName="Allied Team 2"),
                TeamRecord(teamNumber=3333, teamName="Opponent Team 1"),
                TeamRecord(teamNumber=4444, teamName="Opponent Team 2"),
                TeamRecord(teamNumber=5555, teamName="Opponent Team 3"),
            ]

            session.add_all([season, event, organization, user, *team_records])
            await session.commit()
            await session.refresh(organization)

            membership = UserOrganization(
                user_id=user_id,
                organization_id=organization.id,
                role=UserRole.ADMIN,
            )
            session.add(membership)
            await session.commit()
            await session.refresh(membership)

            schedule_entries = [
                MatchSchedule(
                    event_key=event.event_key,
                    match_number=1,
                    match_level="qm",
                    red1_id=4321,
                    red2_id=1111,
                    red3_id=2222,
                    blue1_id=3333,
                    blue2_id=4444,
                    blue3_id=5555,
                ),
                MatchSchedule(
                    event_key=event.event_key,
                    match_number=2,
                    match_level="qm",
                    red1_id=4321,
                    red2_id=1111,
                    red3_id=2222,
                    blue1_id=3333,
                    blue2_id=4444,
                    blue3_id=5555,
                ),
            ]
            session.add_all(schedule_entries)
            await session.commit()

            original_match = MatchData2025(
                season=season.id,
                team_number=4321,
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                notes="Original",
            )
            session.add(original_match)
            await session.commit()

            updated_match = MatchData2025(
                season=season.id,
                team_number=4321,
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                user_id=user_id,
                organization_id=organization.id,
                notes="Updated",
            )

            user_payload = {"id": str(user_id), "user_org": membership.id}
            await edit_2025_match(session, updated_match, user_payload)

            result = await session.execute(
                select(PredictionQueue).where(
                    PredictionQueue.event_key == event.event_key,
                    PredictionQueue.organization_id == organization.id,
                )
            )
            queued_matches = {
                (row.match_number, row.match_level)
                for row in result.scalars().all()
            }
            assert queued_matches == {(2, "qm")}

    asyncio.run(_run_test())


def test_editing_allied_match_queues_for_active_org(setup_database):
    async def _run_test() -> None:
        async with AsyncSessionLocal() as session:
            season = Season(id=7301, year=2025, name="Alliance Season")
            event = FRCEvent(
                event_key="2025allyqueue",
                event_name="Alliance Queue Event",
                short_name="Alliance Queue",
                year=2025,
                week=2,
            )
            org_a = Organization(name="Owner Org", team_number=5314)
            org_b = Organization(name="Editor Org", team_number=9090)
            user_a_id = uuid4()
            user_b_id = uuid4()
            now = datetime.utcnow()
            owner_user = User(
                id=user_a_id,
                email="owner@example.com",
                auth_provider="discord",
                display_name="Owner",
                logged_in_user_org=None,
                created_at=now,
                updated_at=now,
            )
            editor_user = User(
                id=user_b_id,
                email="editor@example.com",
                auth_provider="discord",
                display_name="Editor",
                logged_in_user_org=None,
                created_at=now,
                updated_at=now,
            )

            team_records = [
                TeamRecord(teamNumber=5314, teamName="Team 5314"),
                TeamRecord(teamNumber=9000, teamName="Partner"),
                TeamRecord(teamNumber=9001, teamName="Partner 2"),
                TeamRecord(teamNumber=9002, teamName="Opponent 1"),
                TeamRecord(teamNumber=9003, teamName="Opponent 2"),
                TeamRecord(teamNumber=9004, teamName="Opponent 3"),
            ]

            session.add_all([season, event, org_a, org_b, owner_user, editor_user, *team_records])
            await session.commit()
            await session.refresh(org_a)
            await session.refresh(org_b)

            owner_membership = UserOrganization(
                user_id=user_a_id,
                organization_id=org_a.id,
                role=UserRole.ADMIN,
            )
            editor_membership = UserOrganization(
                user_id=user_b_id,
                organization_id=org_b.id,
                role=UserRole.ADMIN,
            )
            session.add_all([owner_membership, editor_membership])
            await session.commit()
            await session.refresh(editor_membership)

            owner_org_event = OrganizationEvent(
                organization_id=org_a.id,
                event_key=event.event_key,
                active=True,
            )
            editor_org_event = OrganizationEvent(
                organization_id=org_b.id,
                event_key=event.event_key,
                active=True,
            )
            session.add_all([owner_org_event, editor_org_event])
            await session.commit()
            await session.refresh(editor_org_event)

            alliance = OrganizationEventAlliance(
                orgevent_Uid=editor_org_event.id,
                other_organization_id=org_a.id,
                org_invite_status=OrgEventAllianceInviteStatus.ACCEPTED,
            )
            session.add(alliance)
            await session.commit()

            schedule_entries = [
                MatchSchedule(
                    event_key=event.event_key,
                    match_number=1,
                    match_level="qm",
                    red1_id=5314,
                    red2_id=9000,
                    red3_id=9001,
                    blue1_id=9002,
                    blue2_id=9003,
                    blue3_id=9004,
                ),
                MatchSchedule(
                    event_key=event.event_key,
                    match_number=2,
                    match_level="qm",
                    red1_id=5314,
                    red2_id=9000,
                    red3_id=9001,
                    blue1_id=9002,
                    blue2_id=9003,
                    blue3_id=9004,
                ),
            ]
            session.add_all(schedule_entries)
            await session.commit()

            owner_match = MatchData2025(
                season=season.id,
                team_number=5314,
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                user_id=user_a_id,
                organization_id=org_a.id,
                notes="Owner data",
            )
            session.add(owner_match)
            await session.commit()

            updated_match = MatchData2025(
                season=season.id,
                team_number=5314,
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                user_id=user_a_id,
                organization_id=org_a.id,
                notes="Edited by ally",
            )

            user_payload = {"id": str(user_b_id), "user_org": editor_membership.id}

            await batch_update_match(session, [updated_match], user_payload)

            result = await session.execute(
                select(PredictionQueue).where(
                    PredictionQueue.event_key == event.event_key,
                    PredictionQueue.organization_id == org_b.id,
                )
            )
            queued_matches = {
                (row.match_number, row.match_level) for row in result.scalars().all()
            }
            assert queued_matches == {(2, "qm")}

            other_result = await session.execute(
                select(PredictionQueue).where(
                    PredictionQueue.event_key == event.event_key,
                    PredictionQueue.organization_id == org_a.id,
                )
            )
            assert not other_result.scalars().all()

    asyncio.run(_run_test())


def test_match_schedule_sync_queues_modified_matches(monkeypatch, setup_database):
    async def _run_test() -> None:
        async with AsyncSessionLocal() as session:
            event = FRCEvent(
                event_key="2025queuesync",
                event_name="Queue Sync Event",
                short_name="Queue Sync",
                year=2025,
                week=1,
            )
            organization = Organization(name="Sync Org", team_number=9876)
            user_id = uuid4()
            now = datetime.utcnow()
            user = User(
                id=user_id,
                email="sync@example.com",
                auth_provider="discord",
                display_name="Sync User",
                logged_in_user_org=None,
                created_at=now,
                updated_at=now,
            )
            team_records = [
                TeamRecord(teamNumber=9876, teamName="Sync Team"),
                TeamRecord(teamNumber=1010, teamName="Partner 1"),
                TeamRecord(teamNumber=2020, teamName="Partner 2"),
                TeamRecord(teamNumber=3030, teamName="Opponent 1"),
                TeamRecord(teamNumber=4040, teamName="Opponent 2"),
                TeamRecord(teamNumber=5050, teamName="Opponent 3"),
                TeamRecord(teamNumber=6060, teamName="Opponent 4"),
            ]

            session.add_all([event, organization, user, *team_records])
            await session.commit()
            await session.refresh(organization)

            membership = UserOrganization(
                user_id=user_id,
                organization_id=organization.id,
                role=UserRole.ADMIN,
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

            existing_match = MatchSchedule(
                event_key=event.event_key,
                match_number=1,
                match_level="qm",
                red1_id=9876,
                red2_id=1010,
                red3_id=2020,
                blue1_id=3030,
                blue2_id=4040,
                blue3_id=5050,
            )
            session.add(existing_match)
            await session.commit()

            new_schedule_payload = [
                {
                    "comp_level": "qm",
                    "match_number": 1,
                    "alliances": {
                        "red": {
                            "team_keys": [
                                "frc9876",
                                "frc1010",
                                "frc2020",
                            ]
                        },
                        "blue": {
                            "team_keys": [
                                "frc3030",
                                "frc4040",
                                "frc6060",
                            ]
                        },
                    },
                }
            ]

            class MockResponse:
                def __init__(self, payload):
                    self._payload = payload

                def json(self):
                    return self._payload

            class MockAsyncClient:
                def __init__(self, payload):
                    self._payload = payload

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    return False

                async def get(self, url, headers=None):
                    return MockResponse(self._payload)

            monkeypatch.setattr(
                organizationadmin_module.httpx,
                "AsyncClient",
                lambda *args, **kwargs: MockAsyncClient(new_schedule_payload),
            )

            user_payload = {"id": str(user_id), "user_org": membership.id}
            await organizationadmin_module.get_match_schedule(
                user=user_payload, session=session
            )

            result = await session.execute(
                select(PredictionQueue).where(
                    PredictionQueue.event_key == event.event_key,
                    PredictionQueue.organization_id == organization.id,
                )
            )
            queued_matches = {
                (row.match_number, row.match_level)
                for row in result.scalars().all()
            }
            assert queued_matches == {(1, "qm")}

    asyncio.run(_run_test())
