import asyncio
import os
from datetime import datetime

import numpy as np
from sqlmodel import select

from app.models import (
    Alliance,
    EventRankings,
    FRCEvent,
    MatchPredictions2025,
    MatchSchedule,
    Organization,
    RankingPredictionQueue,
    RankingPredictions,
    Season,
    TBAMatchData2025,
    TeamRecord,
)
from app.services import ranking_prediction_daemon
from tests.conftest import AsyncSessionLocal

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")


def _seed_rng() -> np.random.Generator:
    return np.random.default_rng(42)


async def _create_common_setup(session, event_key: str, organization_name: str) -> int:
    season_stmt = select(Season).where(Season.year == 2025)
    season_result = await session.execute(season_stmt)
    season = season_result.scalar_one_or_none()
    if season is None:
        season = Season(id=2025, year=2025, name="Crescendo")
        session.add(season)
        await session.commit()

    event = FRCEvent(event_key=event_key, event_name="Test Event", year=2025, week=1)
    organization = Organization(name=organization_name, team_number=999)

    existing_team_stmt = select(TeamRecord.team_number)
    existing_team_result = await session.execute(existing_team_stmt)
    existing_team_numbers = set(existing_team_result.scalars().all())

    teams = [
        TeamRecord(teamNumber=team, teamName=f"Team {team}")
        for team in (1, 2, 3, 4, 5, 6)
        if team not in existing_team_numbers
    ]

    rankings = [
        EventRankings(
            event_key=event_key,
            rank=index + 1,
            team_number=team,
            ranking_points=0,
            matches_played=0,
            ranking_tiebreaker_1=float(6 - index),
            ranking_tiebreaker_2=float(60 - index),
        )
        for index, team in enumerate((1, 2, 3, 4, 5, 6))
    ]

    session.add(event)
    session.add(organization)
    session.add_all(teams)
    session.add_all(rankings)
    await session.commit()
    await session.refresh(organization)

    org_id = int(organization.id)

    schedule = MatchSchedule(
        event_key=event_key,
        match_number=1,
        match_level="qm",
        red1_id=1,
        red2_id=2,
        red3_id=3,
        blue1_id=4,
        blue2_id=5,
        blue3_id=6,
    )

    predictions = MatchPredictions2025(
        season=season.id,
        event_key=event_key,
        match_number=1,
        match_level="qm",
        organization_id=org_id,
        timestamp=datetime.now(),
        red_alliance_win_pct=1.0,
        blue_alliance_win_pct=0.0,
        n_samples=10_000,
        red_auto_rp=1.0,
        blue_auto_rp=0.0,
        red_endgame_rp=0.0,
        blue_endgame_rp=0.0,
        red_w_coral_rp=0.0,
        blue_w_coral_rp=0.0,
        red_r_coral_rp=0.0,
        blue_r_coral_rp=0.0,
    )

    session.add(schedule)
    session.add(predictions)
    await session.commit()

    return org_id


def test_process_queue_creates_predictions(monkeypatch, setup_database) -> None:
    monkeypatch.setattr(
        ranking_prediction_daemon,
        "async_session_factory",
        AsyncSessionLocal,
        raising=False,
    )
    monkeypatch.setattr(
        ranking_prediction_daemon,
        "_create_rng",
        _seed_rng,
        raising=False,
    )
    monkeypatch.setattr(
        ranking_prediction_daemon,
        "SIMULATION_COUNT",
        100,
        raising=False,
    )

    event_key = "2025rankings"

    async def _run_test() -> None:
        async with AsyncSessionLocal() as session:
            org_id = await _create_common_setup(session, event_key, "Ranking Org")

            session.add_all(
                [
                    TBAMatchData2025(
                        event_key=event_key,
                        match_number=1,
                        match_level="qm",
                        alliance=Alliance.RED,
                        score=None,
                    ),
                    TBAMatchData2025(
                        event_key=event_key,
                        match_number=1,
                        match_level="qm",
                        alliance=Alliance.BLUE,
                        score=None,
                    ),
                    RankingPredictionQueue(
                        event_key=event_key,
                        organization_id=org_id,
                    ),
                ]
            )
            await session.commit()

        work_completed = await ranking_prediction_daemon.process_ranking_prediction_queue()
        assert work_completed is True

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RankingPredictions).where(
                    RankingPredictions.event_key == event_key
                )
            )
            rows = sorted(result.scalars().all(), key=lambda row: row.team_number)
            assert len(rows) == 6

            red_predictions = rows[:3]
            blue_predictions = rows[3:]

            for index, record in enumerate(red_predictions, start=1):
                assert record.rank_5 == index
                assert record.rank_95 == index
                assert record.median_rank == index
                assert record.mean_rp == 4.0

            for index, record in enumerate(blue_predictions, start=4):
                assert record.rank_5 == index
                assert record.rank_95 == index
                assert record.median_rank == index
                assert record.mean_rp == 0.0

            queue_result = await session.execute(select(RankingPredictionQueue))
            assert queue_result.scalars().all() == []

    asyncio.run(_run_test())


def test_process_queue_ignores_playoff_matches(monkeypatch, setup_database) -> None:
    monkeypatch.setattr(
        ranking_prediction_daemon,
        "async_session_factory",
        AsyncSessionLocal,
        raising=False,
    )
    monkeypatch.setattr(
        ranking_prediction_daemon,
        "_create_rng",
        _seed_rng,
        raising=False,
    )
    monkeypatch.setattr(
        ranking_prediction_daemon,
        "SIMULATION_COUNT",
        100,
        raising=False,
    )

    event_key = "2025rankings-playoffs"

    async def _run_test() -> None:
        async with AsyncSessionLocal() as session:
            org_id = await _create_common_setup(session, event_key, "Ranking Org")

            session.add_all(
                [
                    TBAMatchData2025(
                        event_key=event_key,
                        match_number=1,
                        match_level="qm",
                        alliance=Alliance.RED,
                        score=None,
                    ),
                    TBAMatchData2025(
                        event_key=event_key,
                        match_number=1,
                        match_level="qm",
                        alliance=Alliance.BLUE,
                        score=None,
                    ),
                    RankingPredictionQueue(
                        event_key=event_key,
                        organization_id=org_id,
                    ),
                    MatchSchedule(
                        event_key=event_key,
                        match_number=2,
                        match_level="sf",
                        red1_id=1,
                        red2_id=2,
                        red3_id=3,
                        blue1_id=4,
                        blue2_id=5,
                        blue3_id=6,
                    ),
                    TBAMatchData2025(
                        event_key=event_key,
                        match_number=2,
                        match_level="sf",
                        alliance=Alliance.RED,
                        score=None,
                    ),
                    TBAMatchData2025(
                        event_key=event_key,
                        match_number=2,
                        match_level="sf",
                        alliance=Alliance.BLUE,
                        score=None,
                    ),
                ]
            )
            await session.commit()

        work_completed = await ranking_prediction_daemon.process_ranking_prediction_queue()
        assert work_completed is True

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RankingPredictions).where(
                    RankingPredictions.event_key == event_key
                )
            )
            rows = sorted(result.scalars().all(), key=lambda row: row.team_number)
            assert len(rows) == 6

            queue_result = await session.execute(select(RankingPredictionQueue))
            assert queue_result.scalars().all() == []

    asyncio.run(_run_test())


def test_queue_entry_removed_when_no_matches(monkeypatch, setup_database) -> None:
    monkeypatch.setattr(
        ranking_prediction_daemon,
        "async_session_factory",
        AsyncSessionLocal,
        raising=False,
    )
    monkeypatch.setattr(
        ranking_prediction_daemon,
        "SIMULATION_COUNT",
        10,
        raising=False,
    )

    event_key = "2025nomatches"

    async def _run_test() -> None:
        async with AsyncSessionLocal() as session:
            org_id = await _create_common_setup(session, event_key, "Ranking Org 2")

            session.add_all(
                [
                    TBAMatchData2025(
                        event_key=event_key,
                        match_number=1,
                        match_level="qm",
                        alliance=Alliance.RED,
                        score=100,
                    ),
                    TBAMatchData2025(
                        event_key=event_key,
                        match_number=1,
                        match_level="qm",
                        alliance=Alliance.BLUE,
                        score=90,
                    ),
                    RankingPredictionQueue(
                        event_key=event_key,
                        organization_id=org_id,
                    ),
                ]
            )
            await session.commit()

        work_completed = await ranking_prediction_daemon.process_ranking_prediction_queue()
        assert work_completed is False

        async with AsyncSessionLocal() as session:
            predictions_result = await session.execute(
                select(RankingPredictions).where(
                    RankingPredictions.event_key == event_key
                )
            )
            assert predictions_result.scalars().all() == []

            queue_result = await session.execute(select(RankingPredictionQueue))
            assert queue_result.scalars().all() == []

    asyncio.run(_run_test())


def test_incomplete_data_leaves_queue(monkeypatch, setup_database) -> None:
    monkeypatch.setattr(
        ranking_prediction_daemon,
        "async_session_factory",
        AsyncSessionLocal,
        raising=False,
    )
    monkeypatch.setattr(
        ranking_prediction_daemon,
        "SIMULATION_COUNT",
        10,
        raising=False,
    )

    event_key = "2025missing"

    async def _run_test() -> None:
        async with AsyncSessionLocal() as session:
            season_stmt = select(Season).where(Season.year == 2025)
            season_result = await session.execute(season_stmt)
            season = season_result.scalar_one_or_none()
            if season is None:
                season = Season(id=2026, year=2025, name="Crescendo")
                session.add(season)
                await session.commit()

            event = FRCEvent(
                event_key=event_key,
                event_name="Test Event",
                year=2025,
                week=2,
            )
            organization = Organization(name="Ranking Org 3", team_number=123)
            team = TeamRecord(teamNumber=10, teamName="Team 10")

            ranking = EventRankings(
                event_key=event_key,
                rank=1,
                team_number=10,
                ranking_points=0,
                matches_played=0,
                ranking_tiebreaker_1=0.0,
                ranking_tiebreaker_2=0.0,
            )

            schedule = MatchSchedule(
                event_key=event_key,
                match_number=1,
                match_level="qm",
                red1_id=10,
                red2_id=10,
                red3_id=10,
                blue1_id=10,
                blue2_id=10,
                blue3_id=10,
            )

            session.add_all([event, organization, team, ranking, schedule])
            await session.commit()
            await session.refresh(organization)

            session.add(
                RankingPredictionQueue(
                    event_key=event_key,
                    organization_id=int(organization.id),
                )
            )
            await session.commit()

        work_completed = await ranking_prediction_daemon.process_ranking_prediction_queue()
        assert work_completed is False

        async with AsyncSessionLocal() as session:
            queue_result = await session.execute(select(RankingPredictionQueue))
            rows = queue_result.scalars().all()
            # Entry should remain for retry because predictions were missing.
            assert len(rows) == 1

    asyncio.run(_run_test())
