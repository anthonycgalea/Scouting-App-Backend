import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DB_URL", "sqlite+aiosqlite://")

from app.main import app  # noqa: E402
from app.db.database import get_session  # noqa: E402
from app.models import FRCEvent, Organization, OrganizationEvent  # noqa: E402
from app.services.event import get_public_organizations_for_event  # noqa: E402


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

async_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
AsyncSessionLocal = sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_session():
    async with AsyncSessionLocal() as session:
        yield session


async def _create_tables():
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def _drop_tables():
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    app.dependency_overrides[get_session] = override_get_session
    asyncio.run(_create_tables())
    yield
    asyncio.run(_drop_tables())
    app.dependency_overrides.pop(get_session, None)


async def _prepare_public_and_private_orgs():
    async with AsyncSessionLocal() as session:
        event = FRCEvent(event_key="2024test", event_name="Test Event", year=2024, week=1)
        public_org = Organization(name="Public Org", team_number=1234)
        private_org = Organization(name="Private Org", team_number=5678)
        session.add_all([event, public_org, private_org])
        await session.commit()
        await session.refresh(public_org)
        await session.refresh(private_org)

        public_org_event = OrganizationEvent(
            organization_id=public_org.id,
            event_key=event.event_key,
            public_data=True,
        )
        private_org_event = OrganizationEvent(
            organization_id=private_org.id,
            event_key=event.event_key,
            public_data=False,
        )
        session.add_all([public_org_event, private_org_event])
        await session.commit()
        return public_org.id


async def _prepare_private_only_org():
    async with AsyncSessionLocal() as session:
        event = FRCEvent(event_key="2024private", event_name="Private Event", year=2024, week=2)
        hidden_org = Organization(name="Hidden Org", team_number=9012)
        session.add_all([event, hidden_org])
        await session.commit()
        await session.refresh(hidden_org)

        private_org_event = OrganizationEvent(
            organization_id=hidden_org.id,
            event_key=event.event_key,
            public_data=False,
        )
        session.add(private_org_event)
        await session.commit()


def test_get_public_organizations_returns_only_public(setup_database):
    public_org_id = asyncio.run(_prepare_public_and_private_orgs())

    with TestClient(app) as client:
        response = client.get("/event/s/2024test/organizations")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == public_org_id
    assert data[0]["name"] == "Public Org"

    async def verify_service():
        async with AsyncSessionLocal() as session:
            organizations = await get_public_organizations_for_event(session, "2024test")
        assert len(organizations) == 1
        assert organizations[0].id == public_org_id

    asyncio.run(verify_service())


def test_get_public_organizations_without_public_data_returns_empty(setup_database):
    asyncio.run(_prepare_private_only_org())

    with TestClient(app) as client:
        response = client.get("/event/s/2024private/organizations")

    assert response.status_code == 200
    assert response.json() == []

    async def verify_service():
        async with AsyncSessionLocal() as session:
            organizations = await get_public_organizations_for_event(session, "2024private")
        assert organizations == []

    asyncio.run(verify_service())
