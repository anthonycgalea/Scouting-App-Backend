import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models import (
    FRCEvent,
    Organization,
    OrganizationEvent,
    RobotEventImageLink,
    TeamRecord,
    User,
    UserOrganization,
    UserRole,
)
from app.services import team_media
from app.services.team_media import delete_team_image
from tests.conftest import AsyncSessionLocal

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")


class StubS3Client:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete_object(self, Bucket: str, Key: str) -> None:  # pragma: no cover - simple stub
        self.deleted.append((Bucket, Key))


async def _create_base_data(session):
    suffix = uuid4().hex[:8]
    team_number = 4000 + int(suffix[:4], 16) % 2000

    event = FRCEvent(
        event_key=f"2024teamimg{suffix}",
        event_name="Team Image Event",
        short_name="TIE",
        year=2024,
        week=1,
    )
    other_event = FRCEvent(
        event_key=f"2024otherimg{suffix}",
        event_name="Other Event",
        short_name="Other",
        year=2024,
        week=2,
    )
    organization = Organization(name=f"Image Org {suffix}", team_number=team_number)
    user_id = uuid4()
    now = datetime.now(UTC)
    user = User(
        id=user_id,
        email="team-image@example.com",
        auth_provider="discord",
        display_name="Team Image Admin",
        logged_in_user_org=None,
        created_at=now,
        updated_at=now,
    )
    team = TeamRecord(teamNumber=team_number, teamName=f"Team {team_number}")

    session.add_all([event, other_event, organization, user, team])
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

    user.logged_in_user_org = membership.id
    session.add(user)
    await session.commit()

    active_org_event = OrganizationEvent(
        organization_id=organization.id,
        event_key=event.event_key,
        public_data=True,
        active=True,
    )
    session.add(active_org_event)

    await session.commit()

    return {
        "user_id": user_id,
        "membership_id": membership.id,
        "event_key": event.event_key,
        "other_event_key": other_event.event_key,
        "team_number": team.team_number,
    }


def test_delete_team_image_removes_record_and_s3_object(monkeypatch):
    stub = StubS3Client()
    monkeypatch.setattr(team_media, "get_s3_client", lambda: stub)
    monkeypatch.setattr(team_media, "get_team_images_bucket", lambda: "test-bucket")

    async def runner():
        async with AsyncSessionLocal() as session:
            data = await _create_base_data(session)

            object_path = f"{data['event_key']}/{data['team_number']}/sample.png"
            record = RobotEventImageLink(
                team_number=data["team_number"],
                event_key=data["event_key"],
                image_url=f"https://test-bucket.s3.amazonaws.com/{object_path}",
                description="Robot pose",
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)

            user_payload = {"id": str(data["user_id"]), "user_org": data["membership_id"]}

            await delete_team_image(session=session, image_id=record.id, user=user_payload)

            assert await session.get(RobotEventImageLink, record.id) is None
            assert stub.deleted == [("test-bucket", object_path)]

    asyncio.run(runner())


def test_delete_team_image_requires_admin_or_lead(monkeypatch):
    stub = StubS3Client()
    monkeypatch.setattr(team_media, "get_s3_client", lambda: stub)
    monkeypatch.setattr(team_media, "get_team_images_bucket", lambda: "test-bucket")

    async def runner():
        async with AsyncSessionLocal() as session:
            data = await _create_base_data(session)

            membership = await session.get(UserOrganization, data["membership_id"])
            membership.role = UserRole.MEMBER
            await session.commit()
            await session.refresh(membership)

            object_path = f"{data['event_key']}/{data['team_number']}/sample.png"
            record = RobotEventImageLink(
                team_number=data["team_number"],
                event_key=data["event_key"],
                image_url=f"https://test-bucket.s3.amazonaws.com/{object_path}",
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)

            user_payload = {"id": str(data["user_id"]), "user_org": data["membership_id"]}

            with pytest.raises(HTTPException) as exc_info:
                await delete_team_image(session=session, image_id=record.id, user=user_payload)

            assert exc_info.value.status_code == 403
            remaining = await session.get(RobotEventImageLink, record.id)
            assert remaining is not None
            assert stub.deleted == []

    asyncio.run(runner())


def test_delete_team_image_only_allows_active_event_records(monkeypatch):
    stub = StubS3Client()
    monkeypatch.setattr(team_media, "get_s3_client", lambda: stub)
    monkeypatch.setattr(team_media, "get_team_images_bucket", lambda: "test-bucket")

    async def runner():
        async with AsyncSessionLocal() as session:
            data = await _create_base_data(session)

            record = RobotEventImageLink(
                team_number=data["team_number"],
                event_key=data["other_event_key"],
                image_url=(
                    "https://test-bucket.s3.amazonaws.com/"
                    f"{data['other_event_key']}/{data['team_number']}/sample.png"
                ),
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)

            user_payload = {"id": str(data["user_id"]), "user_org": data["membership_id"]}

            with pytest.raises(HTTPException) as exc_info:
                await delete_team_image(session=session, image_id=record.id, user=user_payload)

            assert exc_info.value.status_code == 404
            assert await session.get(RobotEventImageLink, record.id) is not None
            assert stub.deleted == []

    asyncio.run(runner())
