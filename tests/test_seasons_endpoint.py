import asyncio
from typing import List

from fastapi.testclient import TestClient

from app.main import app
from app.models import Season
from app.services.season import get_seasons
from tests.conftest import AsyncSessionLocal


async def _prepare_seasons() -> List[Season]:
    async with AsyncSessionLocal() as session:
        seasons = [
            Season(year=2023, name="Charged Up"),
            Season(year=2024, name="Crescendo"),
        ]
        session.add_all(seasons)
        await session.commit()
        for season in seasons:
            await session.refresh(season)
        return seasons


def test_list_seasons_returns_season_objects(setup_database):
    created_seasons = asyncio.run(_prepare_seasons())

    with TestClient(app) as client:
        response = client.get("/seasons")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == len(created_seasons)
    assert [season["id"] for season in data] == [season.id for season in created_seasons]
    assert [season["year"] for season in data] == [season.year for season in created_seasons]
    assert [season["name"] for season in data] == [season.name for season in created_seasons]

    async def verify_service():
        async with AsyncSessionLocal() as session:
            return await get_seasons(session)

    seasons = asyncio.run(verify_service())
    assert [season.id for season in seasons] == [season.id for season in created_seasons]
