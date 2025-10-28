"""Background worker for computing ranking prediction simulations."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session_factory
from app.models import (
    Alliance,
    EventRankings,
    FRCEvent,
    MatchSchedule,
    RankingPredictionQueue,
    RankingPredictions,
)
from app.services.event import TBA_MATCH_DATA_MODELS_BY_YEAR
from app.services.match_prediction import MATCH_PREDICTION_MODELS_BY_YEAR

logger = logging.getLogger(__name__)

SLEEP_INTERVAL_SECONDS = 20 * 60
SIMULATION_COUNT = 10_000

# Only qualification matches impact ranking point totals. Playoff matches
# (quarterfinals, semifinals, finals, etc.) should not be considered when
# simulating future rankings.
QUALIFICATION_MATCH_LEVELS = {"qm"}


@dataclass(frozen=True)
class QueuedRankingPrediction:
    """Representation of a queued ranking prediction job."""

    event_key: str
    organization_id: int


@dataclass(frozen=True)
class _MatchSimulationInput:
    """Simulation inputs for a single unplayed match."""

    match_level: str
    match_number: int
    red_teams: Tuple[int, ...]
    blue_teams: Tuple[int, ...]
    red_win_prob: float
    blue_win_prob: float
    red_auto_rp_prob: float
    blue_auto_rp_prob: float
    red_endgame_rp_prob: float
    blue_endgame_rp_prob: float
    red_coral_rp_prob: float
    blue_coral_rp_prob: float


class NoUnplayedMatchesError(Exception):
    """Raised when an event has no remaining matches to simulate."""


class IncompleteDataError(Exception):
    """Raised when required data for a simulation is missing."""


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional scope around a series of operations."""

    session: AsyncSession = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


async def _load_queued_jobs(session: AsyncSession) -> List[QueuedRankingPrediction]:
    statement = select(
        RankingPredictionQueue.event_key, RankingPredictionQueue.organization_id
    ).order_by(RankingPredictionQueue.event_key, RankingPredictionQueue.organization_id)
    result = await session.execute(statement)
    rows = result.all()
    return [
        QueuedRankingPrediction(event_key=event_key, organization_id=organization_id)
        for event_key, organization_id in rows
    ]


async def _mark_job_complete(
    session: AsyncSession, job: QueuedRankingPrediction
) -> None:
    await session.execute(
        delete(RankingPredictionQueue).where(
            RankingPredictionQueue.event_key == job.event_key,
            RankingPredictionQueue.organization_id == job.organization_id,
        )
    )


def _create_rng() -> np.random.Generator:
    """Return a fresh random number generator for simulations."""

    return np.random.default_rng()


def _normalize_probability(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _normalize_outcome_probabilities(red: float, blue: float) -> Tuple[float, float]:
    red = _normalize_probability(red)
    blue = _normalize_probability(blue)
    total = red + blue
    if total > 1.0 and total > 0:
        red /= total
        blue /= total
    return red, blue


def _match_is_played(
    alliance_records: Mapping[Alliance, Optional[object]],
) -> bool:
    """Return ``True`` when a match already has recorded scores."""

    for record in alliance_records.values():
        if record is None:
            return False
        score = getattr(record, "score", None)
        if score is None:
            return False
    return True


async def _collect_simulation_inputs(
    session: AsyncSession,
    *,
    event: FRCEvent,
    organization_id: int,
) -> Tuple[List[_MatchSimulationInput], Dict[int, EventRankings]]:
    prediction_model = MATCH_PREDICTION_MODELS_BY_YEAR.get(event.year)
    if prediction_model is None:
        raise IncompleteDataError(
            f"Match predictions are not available for event year {event.year}."
        )

    tba_model = TBA_MATCH_DATA_MODELS_BY_YEAR.get(event.year)
    if tba_model is None:
        raise IncompleteDataError(
            f"TBA match data is not available for event year {event.year}."
        )

    prediction_stmt = (
        select(prediction_model)
        .where(
            prediction_model.event_key == event.event_key,
            prediction_model.organization_id == organization_id,
        )
        .order_by(
            prediction_model.match_level,
            prediction_model.match_number,
        )
    )
    prediction_result = await session.execute(prediction_stmt)
    predictions = {
        (row.match_level, row.match_number): row for row in prediction_result.scalars()
    }

    if not predictions:
        raise IncompleteDataError("No match predictions are stored for this organization.")

    schedule_stmt = select(MatchSchedule).where(
        MatchSchedule.event_key == event.event_key
    )
    schedule_result = await session.execute(schedule_stmt)
    all_schedule_entries = list(schedule_result.scalars().all())
    if not all_schedule_entries:
        raise IncompleteDataError("No match schedule data found for event.")

    schedule_entries = [
        entry
        for entry in all_schedule_entries
        if (entry.match_level or "").lower() in QUALIFICATION_MATCH_LEVELS
    ]

    if not schedule_entries:
        raise NoUnplayedMatchesError(
            f"No qualification matches remaining for event {event.event_key}."
        )

    tba_stmt = select(tba_model).where(tba_model.event_key == event.event_key)
    tba_result = await session.execute(tba_stmt)
    tba_entries = list(tba_result.scalars().all())
    tba_map: Dict[Tuple[str, int, Alliance], object] = {
        (entry.match_level, entry.match_number, entry.alliance): entry
        for entry in tba_entries
    }

    ranking_stmt = select(EventRankings).where(
        EventRankings.event_key == event.event_key
    )
    ranking_result = await session.execute(ranking_stmt)
    rankings = {
        row.team_number: row for row in ranking_result.scalars().all()
    }
    if not rankings:
        raise IncompleteDataError("Event rankings data is unavailable.")

    matches: List[_MatchSimulationInput] = []

    for schedule in schedule_entries:
        key = (schedule.match_level, schedule.match_number)
        prediction = predictions.get(key)
        if prediction is None:
            # Predictions not computed for this match yet; retry later.
            raise IncompleteDataError(
                f"Missing prediction for match {schedule.match_level} {schedule.match_number}."
            )

        alliance_records = {
            Alliance.RED: tba_map.get((schedule.match_level, schedule.match_number, Alliance.RED)),
            Alliance.BLUE: tba_map.get((schedule.match_level, schedule.match_number, Alliance.BLUE)),
        }

        if _match_is_played(alliance_records):
            continue

        red_win, blue_win = _normalize_outcome_probabilities(
            getattr(prediction, "red_alliance_win_pct", 0.0),
            getattr(prediction, "blue_alliance_win_pct", 0.0),
        )

        match_input = _MatchSimulationInput(
            match_level=schedule.match_level,
            match_number=schedule.match_number,
            red_teams=(schedule.red1_id, schedule.red2_id, schedule.red3_id),
            blue_teams=(schedule.blue1_id, schedule.blue2_id, schedule.blue3_id),
            red_win_prob=red_win,
            blue_win_prob=blue_win,
            red_auto_rp_prob=_normalize_probability(
                getattr(prediction, "red_auto_rp", 0.0)
            ),
            blue_auto_rp_prob=_normalize_probability(
                getattr(prediction, "blue_auto_rp", 0.0)
            ),
            red_endgame_rp_prob=_normalize_probability(
                getattr(prediction, "red_endgame_rp", 0.0)
            ),
            blue_endgame_rp_prob=_normalize_probability(
                getattr(prediction, "blue_endgame_rp", 0.0)
            ),
            red_coral_rp_prob=_normalize_probability(
                getattr(prediction, "red_w_coral_rp", 0.0)
            ),
            blue_coral_rp_prob=_normalize_probability(
                getattr(prediction, "blue_w_coral_rp", 0.0)
            ),
        )

        matches.append(match_input)

    if not matches:
        raise NoUnplayedMatchesError(
            f"All matches for event {event.event_key} already have results."
        )

    return matches, rankings


def _compute_percentile(ranks: np.ndarray, percentile: float) -> int:
    sorted_ranks = np.sort(ranks)
    if sorted_ranks.size == 0:
        return 0
    index = int(np.floor((percentile / 100.0) * (sorted_ranks.size - 1)))
    index = max(0, min(index, sorted_ranks.size - 1))
    return int(sorted_ranks[index])


def _compute_median_rank(ranks: np.ndarray) -> int:
    sorted_ranks = np.sort(ranks)
    if sorted_ranks.size == 0:
        return 0
    mid = sorted_ranks.size // 2
    if sorted_ranks.size % 2 == 1:
        return int(sorted_ranks[mid])
    return int(round((sorted_ranks[mid - 1] + sorted_ranks[mid]) / 2))


def _simulate_rankings(
    matches: Sequence[_MatchSimulationInput],
    rankings: Mapping[int, EventRankings],
    *,
    n_simulations: int,
) -> Dict[int, Dict[str, float]]:
    team_numbers = set(rankings.keys())
    for match in matches:
        team_numbers.update(match.red_teams)
        team_numbers.update(match.blue_teams)

    if not team_numbers:
        return {}

    ordered_teams = sorted(team_numbers)
    team_to_index = {team: idx for idx, team in enumerate(ordered_teams)}

    base_rp = np.zeros(len(ordered_teams), dtype=float)
    tie_breaker_1 = np.zeros(len(ordered_teams), dtype=float)
    tie_breaker_2 = np.zeros(len(ordered_teams), dtype=float)

    for team, ranking in rankings.items():
        idx = team_to_index.get(team)
        if idx is None:
            continue
        base_rp[idx] = float(getattr(ranking, "ranking_points", 0.0) or 0.0)
        tie_breaker_1[idx] = float(getattr(ranking, "ranking_tiebreaker_1", 0.0) or 0.0)
        tie_breaker_2[idx] = float(getattr(ranking, "ranking_tiebreaker_2", 0.0) or 0.0)

    rng = _create_rng()
    rp_totals = np.tile(base_rp, (n_simulations, 1))

    for match in matches:
        random_outcomes = rng.random(n_simulations)
        red_threshold = match.red_win_prob
        blue_threshold = match.red_win_prob + match.blue_win_prob
        blue_threshold = min(blue_threshold, 1.0)

        red_wins = random_outcomes < red_threshold
        blue_wins = (random_outcomes >= red_threshold) & (
            random_outcomes < blue_threshold
        )

        red_base = red_wins.astype(float) * 3.0
        blue_base = blue_wins.astype(float) * 3.0

        red_auto = (rng.random(n_simulations) < match.red_auto_rp_prob).astype(float)
        blue_auto = (rng.random(n_simulations) < match.blue_auto_rp_prob).astype(float)
        red_endgame = (
            rng.random(n_simulations) < match.red_endgame_rp_prob
        ).astype(float)
        blue_endgame = (
            rng.random(n_simulations) < match.blue_endgame_rp_prob
        ).astype(float)
        red_coral = (
            rng.random(n_simulations) < match.red_coral_rp_prob
        ).astype(float)
        blue_coral = (
            rng.random(n_simulations) < match.blue_coral_rp_prob
        ).astype(float)

        red_total = red_base + red_auto + red_endgame + red_coral
        blue_total = blue_base + blue_auto + blue_endgame + blue_coral

        red_indices = [team_to_index[team] for team in match.red_teams]
        blue_indices = [team_to_index[team] for team in match.blue_teams]

        rp_totals[:, red_indices] += red_total[:, None]
        rp_totals[:, blue_indices] += blue_total[:, None]

    ranks = np.zeros_like(rp_totals, dtype=int)

    for sim_index in range(n_simulations):
        ordering = np.lexsort(
            (
                -tie_breaker_2,
                -tie_breaker_1,
                -rp_totals[sim_index],
            )
        )
        ranks[sim_index, ordering] = np.arange(1, len(ordering) + 1)

    statistics: Dict[int, Dict[str, float]] = {}

    for team in ordered_teams:
        idx = team_to_index[team]
        team_ranks = ranks[:, idx]
        statistics[team] = {
            "rank_5": float(_compute_percentile(team_ranks, 5)),
            "rank_95": float(_compute_percentile(team_ranks, 95)),
            "median_rank": float(_compute_median_rank(team_ranks)),
            "mean_rank": float(np.mean(team_ranks)),
            "mean_rp": float(np.mean(rp_totals[:, idx])),
        }

    return statistics


async def _run_ranking_simulation(
    session: AsyncSession,
    *,
    event_key: str,
    organization_id: int,
    n_simulations: int,
) -> Dict[int, Dict[str, float]]:
    event = await session.get(FRCEvent, event_key)
    if event is None:
        raise IncompleteDataError(f"Event {event_key} does not exist.")

    matches, rankings = await _collect_simulation_inputs(
        session, event=event, organization_id=organization_id
    )
    return _simulate_rankings(matches, rankings, n_simulations=n_simulations)


async def _save_ranking_predictions(
    session: AsyncSession,
    *,
    event_key: str,
    organization_id: int,
    statistics: Mapping[int, Mapping[str, float]],
) -> int:
    if not statistics:
        return 0

    existing_stmt = select(RankingPredictions).where(
        RankingPredictions.event_key == event_key,
        RankingPredictions.organization_id == organization_id,
    )
    existing_result = await session.execute(existing_stmt)
    existing_records = {
        row.team_number: row for row in existing_result.scalars().all()
    }

    updated = 0
    now = datetime.now()

    for team_number, stats in statistics.items():
        record = existing_records.get(team_number)
        if record is None:
            record = RankingPredictions(
                event_key=event_key,
                organization_id=organization_id,
                team_number=team_number,
                rank_5=int(stats["rank_5"]),
                rank_95=int(stats["rank_95"]),
                median_rank=int(stats["median_rank"]),
                mean_rank=float(stats["mean_rank"]),
                mean_rp=float(stats["mean_rp"]),
            )
        else:
            record.rank_5 = int(stats["rank_5"])
            record.rank_95 = int(stats["rank_95"])
            record.median_rank = int(stats["median_rank"])
            record.mean_rank = float(stats["mean_rank"])
            record.mean_rp = float(stats["mean_rp"])

        record.timestamp = now
        session.add(record)
        updated += 1

    return updated


async def process_ranking_prediction_queue() -> bool:
    """Process all queued ranking prediction jobs once."""

    async with session_scope() as session:
        jobs = await _load_queued_jobs(session)
        if not jobs:
            logger.info("No ranking prediction jobs in queue.")
            return False

        logger.info("Processing %d ranking prediction jobs.", len(jobs))
        work_completed = False

        for job in jobs:
            logger.info(
                "Running ranking predictions for event %s (organization %s)",
                job.event_key,
                job.organization_id,
            )
            start_time = time.perf_counter()
            try:
                statistics = await _run_ranking_simulation(
                    session,
                    event_key=job.event_key,
                    organization_id=job.organization_id,
                    n_simulations=SIMULATION_COUNT,
                )

                updated = await _save_ranking_predictions(
                    session,
                    event_key=job.event_key,
                    organization_id=job.organization_id,
                    statistics=statistics,
                )
                await _mark_job_complete(session, job)
                await session.commit()

                elapsed = time.perf_counter() - start_time
                logger.info(
                    "Completed ranking predictions for %s/%s: %d rows in %.2f seconds.",
                    job.event_key,
                    job.organization_id,
                    updated,
                    elapsed,
                )
                if updated:
                    work_completed = True
            except NoUnplayedMatchesError as exc:
                logger.info("%s", exc)
                try:
                    await _mark_job_complete(session, job)
                    await session.commit()
                except SQLAlchemyError:
                    logger.exception(
                        "Database error while removing completed job for %s/%s",
                        job.event_key,
                        job.organization_id,
                    )
                    await session.rollback()
            except IncompleteDataError as exc:
                logger.warning(
                    "Skipping ranking prediction for %s/%s due to incomplete data: %s",
                    job.event_key,
                    job.organization_id,
                    exc,
                )
                await session.rollback()
            except SQLAlchemyError:
                logger.exception(
                    "Database error while processing ranking predictions for %s/%s",
                    job.event_key,
                    job.organization_id,
                )
                await session.rollback()
            except Exception:
                logger.exception(
                    "Unexpected error while processing ranking predictions for %s/%s",
                    job.event_key,
                    job.organization_id,
                )
                await session.rollback()

        return work_completed


__all__ = [
    "QueuedRankingPrediction",
    "SLEEP_INTERVAL_SECONDS",
    "SIMULATION_COUNT",
    "process_ranking_prediction_queue",
    "session_scope",
]
