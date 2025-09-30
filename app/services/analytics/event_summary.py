"""Utilities for summarizing event match data using pandas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import pandas as pd
from fastapi import HTTPException
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import (
    UserOrganization,
)
from ..event import (
    MATCH_DATA_MODELS_BY_YEAR,
    get_active_event_key_for_user,
    get_event_or_404,
)


@dataclass(frozen=True)
class YearlyScoringConfig:
    """Defines how to score match data for a specific game year."""

    auto_weights: Mapping[str, float]
    teleop_weights: Mapping[str, float]
    endgame_points: Mapping[str, float]
    game_piece_fields: Sequence[str]


def _default_yearly_configs() -> Dict[int, YearlyScoringConfig]:
    """Return the scoring configuration for each supported year."""

    return {
        2025: YearlyScoringConfig(
            auto_weights={
                "al4c": 7.0,
                "al3c": 6.0,
                "al2c": 4.0,
                "al1c": 3.0,
                "aNet": 4.0,
                "aProcessor": 2.0,
            },
            teleop_weights={
                "tl4c": 5.0,
                "tl3c": 4.0,
                "tl2c": 3.0,
                "tl1c": 2.0,
                "tNet": 4.0,
                "tProcessor": 2.0,
            },
            endgame_points={
                "NONE": 0.0,
                "PARK": 2.0,
                "SHALLOW": 6.0,
                "DEEP": 12.0,
            },
            game_piece_fields=(
                "al4c",
                "al3c",
                "al2c",
                "al1c",
                "aNet",
                "aProcessor",
                "tl4c",
                "tl3c",
                "tl2c",
                "tl1c",
                "tNet",
                "tProcessor",
            ),
        ),
        2026: YearlyScoringConfig(
            auto_weights={},
            teleop_weights={},
            endgame_points={"NONE": 0.0},
            game_piece_fields=(),
        ),
    }


SCORING_CONFIGS: Dict[int, YearlyScoringConfig] = _default_yearly_configs()

MATCH_LEVEL_ORDER = {
    "QM": 0,
    "QF": 1,
    "SF": 2,
    "F": 3,
}


class TeamEventSummary(SQLModel):
    team_number: int
    matches_played: int
    autonomous_points_average: float
    teleop_points_average: float
    endgame_points_average: float
    game_piece_average: float
    total_points_average: float


class TeamEventZScoreSummary(SQLModel):
    team_number: int
    matches_played: int
    autonomous_points_average: float
    teleop_points_average: float
    endgame_points_average: float
    game_piece_average: float
    total_points_average: float
    autonomous_level_4_coral_average: float = 0.0
    autonomous_level_3_coral_average: float = 0.0
    autonomous_level_2_coral_average: float = 0.0
    autonomous_level_1_coral_average: float = 0.0
    teleop_level_4_coral_average: float = 0.0
    teleop_level_3_coral_average: float = 0.0
    teleop_level_2_coral_average: float = 0.0
    teleop_level_1_coral_average: float = 0.0
    autonomous_net_average: float = 0.0
    teleop_net_average: float = 0.0
    autonomous_processor_average: float = 0.0
    teleop_processor_average: float = 0.0
    teleop_cycles_average: float = 0.0
    autonomous_points_z: float
    teleop_points_z: float
    endgame_points_z: float
    game_piece_z: float
    total_points_z: float
    autonomous_level_4_coral_z: float = 0.0
    autonomous_level_3_coral_z: float = 0.0
    autonomous_level_2_coral_z: float = 0.0
    autonomous_level_1_coral_z: float = 0.0
    teleop_level_4_coral_z: float = 0.0
    teleop_level_3_coral_z: float = 0.0
    teleop_level_2_coral_z: float = 0.0
    teleop_level_1_coral_z: float = 0.0
    autonomous_net_z: float = 0.0
    teleop_net_z: float = 0.0
    autonomous_processor_z: float = 0.0
    teleop_processor_z: float = 0.0
    teleop_cycles_z: float = 0.0


class DistributionStatistics(SQLModel):
    min: float = 0.0
    lowerQuartile: float = 0.0
    median: float = 0.0
    upperQuartile: float = 0.0
    max: float = 0.0
    average: float = 0.0


class StatisticZScoreExtremes(SQLModel):
    min: float = 0.0
    max: float = 0.0


class TeamEventDetailedSummary(SQLModel):
    team_number: int
    matches_played: int
    autonomous_points: DistributionStatistics
    teleop_points: DistributionStatistics
    game_pieces: DistributionStatistics
    total_points: DistributionStatistics


class TeamMatchBreakdown(SQLModel):
    team_number: int
    match_level: str
    match_number: int
    autonomous_points: float
    teleop_points: float
    endgame_points: float
    game_pieces: int
    total_points: float
    notes: str


class TeamMatchHistory(SQLModel):
    team_number: int
    matches_played: int
    matches: List[TeamMatchBreakdown]


class EventTeamZScoreResponse(SQLModel):
    teams: List[TeamEventZScoreSummary]
    z_score_extremes: Dict[str, StatisticZScoreExtremes]


def _normalize_user_payload(user: object) -> Dict[str, object]:
    if isinstance(user, dict):
        return user

    return {
        "id": getattr(user, "id", None),
        "user_org": getattr(user, "logged_in_user_org", None),
    }


def _coerce_membership_id(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise HTTPException(status_code=400, detail="Invalid organization membership identifier")


async def _get_membership(session: AsyncSession, user_payload: Dict[str, object]) -> UserOrganization:
    membership_id = user_payload.get("user_org")
    if membership_id is None:
        raise HTTPException(status_code=404, detail="User is not logged into an organization")

    membership = await session.get(UserOrganization, _coerce_membership_id(membership_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")
    return membership


def _weighted_sum(df: pd.DataFrame, weights: Mapping[str, float]) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)

    total = pd.Series(0.0, index=df.index, dtype=float)
    for field, weight in weights.items():
        if field not in df.columns:
            continue
        values = pd.to_numeric(df[field], errors="coerce").fillna(0.0)
        total = total + values * weight
    return total


def _calculate_game_piece_counts(df: pd.DataFrame, fields: Iterable[str]) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)

    total = pd.Series(0.0, index=df.index, dtype=float)
    for field in fields:
        if field not in df.columns:
            continue
        values = pd.to_numeric(df[field], errors="coerce").fillna(0.0)
        total = total + values
    return total


def _normalize_endgame_value(value: object) -> str:
    if hasattr(value, "value"):
        value = getattr(value, "value")
    if isinstance(value, str):
        normalized = value.strip().upper()
        return normalized or "NONE"
    return "NONE"


def _endgame_points(df: pd.DataFrame, config: YearlyScoringConfig) -> pd.Series:
    if df.empty or "endgame" not in df.columns:
        return pd.Series(dtype=float)

    normalized = df["endgame"].map(_normalize_endgame_value)
    return normalized.map(lambda value: config.endgame_points.get(value, 0.0)).astype(float)


def _collect_scoring_fields(config: YearlyScoringConfig) -> Sequence[str]:
    fields = set(config.game_piece_fields)
    fields.update(config.auto_weights.keys())
    fields.update(config.teleop_weights.keys())
    return sorted(fields)


def _records_to_dataframe(records: Sequence[SQLModel], config: YearlyScoringConfig) -> pd.DataFrame:
    scoring_fields = _collect_scoring_fields(config)

    rows = []
    for record in records:
        row = {
            "team_number": getattr(record, "team_number", None),
            "match_number": getattr(record, "match_number", None),
            "match_level": getattr(record, "match_level", None),
            "endgame": getattr(record, "endgame", None),
            "notes": getattr(record, "notes", ""),
        }

        for field in scoring_fields:
            row[field] = getattr(record, field, 0) or 0

        rows.append(row)

    return pd.DataFrame(rows)


def _build_team_summary_dataframe(
    df: pd.DataFrame, config: YearlyScoringConfig
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    working = df.copy()
    working["autonomous_points"] = _weighted_sum(working, config.auto_weights)
    working["teleop_points"] = _weighted_sum(working, config.teleop_weights)
    working["endgame_points"] = _endgame_points(working, config)
    working["game_piece_count"] = _calculate_game_piece_counts(
        working, config.game_piece_fields
    )
    teleop_cycle_fields = [
        field
        for field in (
            "tl4c",
            "tl3c",
            "tl2c",
            "tl1c",
            "tNet",
            "tProcessor",
        )
        if field in working.columns
    ]
    if teleop_cycle_fields:
        working["teleop_cycles"] = _calculate_game_piece_counts(
            working, teleop_cycle_fields
        )
    working["total_points"] = (
        working["autonomous_points"]
        + working["teleop_points"]
        + working["endgame_points"]
    )

    aggregations = {
        "matches_played": ("match_number", "count"),
        "autonomous_points_average": ("autonomous_points", "mean"),
        "teleop_points_average": ("teleop_points", "mean"),
        "endgame_points_average": ("endgame_points", "mean"),
        "game_piece_average": ("game_piece_count", "mean"),
        "total_points_average": ("total_points", "mean"),
    }

    field_average_mapping = {
        "al4c": "autonomous_level_4_coral_average",
        "al3c": "autonomous_level_3_coral_average",
        "al2c": "autonomous_level_2_coral_average",
        "al1c": "autonomous_level_1_coral_average",
        "tl4c": "teleop_level_4_coral_average",
        "tl3c": "teleop_level_3_coral_average",
        "tl2c": "teleop_level_2_coral_average",
        "tl1c": "teleop_level_1_coral_average",
        "aNet": "autonomous_net_average",
        "tNet": "teleop_net_average",
        "aProcessor": "autonomous_processor_average",
        "tProcessor": "teleop_processor_average",
    }

    for field, alias in field_average_mapping.items():
        if field in working.columns:
            aggregations[alias] = (field, "mean")

    if "teleop_cycles" in working.columns:
        aggregations["teleop_cycles_average"] = ("teleop_cycles", "mean")

    summary = (
        working.groupby("team_number")
        .agg(**aggregations)
        .reset_index()
        .sort_values("team_number")
    )

    average_columns = [
        column for column in summary.columns if column.endswith("_average")
    ]
    for column in average_columns:
        summary[column] = summary[column].fillna(0.0).round(2)

    summary["matches_played"] = summary["matches_played"].fillna(0).astype(int)
    summary["team_number"] = summary["team_number"].fillna(0).astype(int)

    return summary


def _summarize_by_team(df: pd.DataFrame, config: YearlyScoringConfig) -> List[Dict[str, object]]:
    summary = _build_team_summary_dataframe(df, config)
    if summary.empty:
        return []
    return summary.to_dict(orient="records")


def _append_z_scores(
    summary: pd.DataFrame, columns: Sequence[str]
) -> Tuple[pd.DataFrame, Dict[str, Dict[str, float]]]:
    if summary.empty:
        return summary, {}

    zscore_columns = [column for column in columns if column in summary.columns]
    if not zscore_columns:
        return summary, {}

    numeric = summary[zscore_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    means = numeric.mean()
    stds = numeric.std(ddof=0)
    safe_stds = stds.replace(0, pd.NA)

    z_scores = (numeric - means) / safe_stds
    z_scores = z_scores.fillna(0.0)

    for column in zscore_columns:
        summary[f"{column}_z"] = z_scores[column].round(2)

    extremes: Dict[str, Dict[str, float]] = {}
    for column in zscore_columns:
        z_column = summary[f"{column}_z"]
        extremes[column] = {
            "min": _round_stat(z_column.min()),
            "max": _round_stat(z_column.max()),
        }

    return summary, extremes


def _round_stat(value: float) -> float:
    if pd.isna(value):
        return 0.0
    return round(float(value), 2)


def _calculate_distribution_statistics(series: pd.Series) -> DistributionStatistics:
    if series.empty:
        return DistributionStatistics()

    numeric_series = pd.to_numeric(series, errors="coerce").dropna()
    if numeric_series.empty:
        return DistributionStatistics()

    return DistributionStatistics(
        min=_round_stat(numeric_series.min()),
        lowerQuartile=_round_stat(
            numeric_series.quantile(0.25, interpolation="linear")
        ),
        median=_round_stat(numeric_series.median()),
        upperQuartile=_round_stat(
            numeric_series.quantile(0.75, interpolation="linear")
        ),
        max=_round_stat(numeric_series.max()),
        average=_round_stat(numeric_series.mean()),
    )


def _summarize_detailed_by_team(
    df: pd.DataFrame, config: YearlyScoringConfig
) -> List[TeamEventDetailedSummary]:
    if df.empty:
        return []

    df = df.copy()
    df["autonomous_points"] = _weighted_sum(df, config.auto_weights)
    df["teleop_points"] = _weighted_sum(df, config.teleop_weights)
    df["endgame_points"] = _endgame_points(df, config)
    df["game_piece_count"] = _calculate_game_piece_counts(df, config.game_piece_fields)
    df["total_points"] = (
        df["autonomous_points"] + df["teleop_points"] + df["endgame_points"]
    )

    summaries: List[TeamEventDetailedSummary] = []
    grouped = df.groupby("team_number")
    for team_number, group in grouped:
        summaries.append(
            TeamEventDetailedSummary(
                team_number=int(team_number) if pd.notna(team_number) else 0,
                matches_played=int(group["match_number"].count()),
                autonomous_points=_calculate_distribution_statistics(
                    group["autonomous_points"]
                ),
                teleop_points=_calculate_distribution_statistics(group["teleop_points"]),
                game_pieces=_calculate_distribution_statistics(
                    group["game_piece_count"]
                ),
                total_points=_calculate_distribution_statistics(group["total_points"]),
            )
        )

    summaries.sort(key=lambda entry: entry.team_number)
    return summaries


async def _load_event_dataframe(
    session: AsyncSession, user_payload: Dict[str, object]
) -> Tuple[pd.DataFrame, YearlyScoringConfig]:
    event_key = await get_active_event_key_for_user(session, user_payload)
    event = await get_event_or_404(session, event_key)
    membership = await _get_membership(session, user_payload)

    match_model = MATCH_DATA_MODELS_BY_YEAR.get(event.year)
    if match_model is None:
        raise HTTPException(status_code=404, detail="Match data is not available for this event")

    scoring_config = SCORING_CONFIGS.get(event.year)
    if (
        scoring_config is None
        or (
            not scoring_config.auto_weights
            and not scoring_config.teleop_weights
            and not scoring_config.game_piece_fields
        )
    ):
        raise HTTPException(
            status_code=404,
            detail="Team summaries are not configured for this event year",
        )

    statement = select(match_model).where(
        match_model.event_key == event_key,
        match_model.organization_id == membership.organization_id,
    )
    result = await session.execute(statement)
    records = result.scalars().all()

    if not records:
        return pd.DataFrame(), scoring_config

    dataframe = _records_to_dataframe(records, scoring_config)
    return dataframe, scoring_config


async def get_team_event_summary(
    session: AsyncSession,
    user: object,
) -> List[TeamEventSummary]:
    user_payload = _normalize_user_payload(user)
    dataframe, scoring_config = await _load_event_dataframe(session, user_payload)

    if dataframe.empty:
        return []

    summaries = _summarize_by_team(dataframe, scoring_config)
    return [TeamEventSummary(**row) for row in summaries]


async def get_team_event_z_scores(
    session: AsyncSession,
    user: object,
) -> EventTeamZScoreResponse:
    user_payload = _normalize_user_payload(user)
    dataframe, scoring_config = await _load_event_dataframe(session, user_payload)

    summary_df = _build_team_summary_dataframe(dataframe, scoring_config)
    if summary_df.empty:
        return EventTeamZScoreResponse(teams=[], z_score_extremes={})

    stat_columns = [
        "autonomous_points_average",
        "teleop_points_average",
        "endgame_points_average",
        "game_piece_average",
        "total_points_average",
        "autonomous_level_4_coral_average",
        "autonomous_level_3_coral_average",
        "autonomous_level_2_coral_average",
        "autonomous_level_1_coral_average",
        "teleop_level_4_coral_average",
        "teleop_level_3_coral_average",
        "teleop_level_2_coral_average",
        "teleop_level_1_coral_average",
        "autonomous_net_average",
        "teleop_net_average",
        "autonomous_processor_average",
        "teleop_processor_average",
        "teleop_cycles_average",
    ]
    summary_with_z, extremes = _append_z_scores(summary_df, stat_columns)

    teams = [
        TeamEventZScoreSummary(**record)
        for record in summary_with_z.to_dict(orient="records")
    ]

    extremes_payload = {
        column: StatisticZScoreExtremes(**values) for column, values in extremes.items()
    }

    return EventTeamZScoreResponse(teams=teams, z_score_extremes=extremes_payload)


async def get_team_event_detailed_summary(
    session: AsyncSession,
    user: object,
) -> List[TeamEventDetailedSummary]:
    user_payload = _normalize_user_payload(user)
    dataframe, scoring_config = await _load_event_dataframe(session, user_payload)

    if dataframe.empty:
        return []

    return _summarize_detailed_by_team(dataframe, scoring_config)


def _sort_match_level(value: object) -> int:
    if value is None:
        return len(MATCH_LEVEL_ORDER)
    if hasattr(value, "value"):
        value = getattr(value, "value")
    if isinstance(value, str):
        normalized = value.strip().upper()
        return MATCH_LEVEL_ORDER.get(normalized, len(MATCH_LEVEL_ORDER))
    return len(MATCH_LEVEL_ORDER)


async def get_team_event_match_history(
    session: AsyncSession,
    user: object,
) -> List[TeamMatchHistory]:
    user_payload = _normalize_user_payload(user)
    dataframe, scoring_config = await _load_event_dataframe(session, user_payload)

    if dataframe.empty:
        return []

    df = dataframe.copy()
    df["autonomous_points"] = _weighted_sum(df, scoring_config.auto_weights)
    df["teleop_points"] = _weighted_sum(df, scoring_config.teleop_weights)
    df["endgame_points"] = _endgame_points(df, scoring_config)
    df["game_piece_count"] = _calculate_game_piece_counts(
        df, scoring_config.game_piece_fields
    )
    df["total_points"] = (
        df["autonomous_points"] + df["teleop_points"] + df["endgame_points"]
    )

    df["team_number"] = pd.to_numeric(df["team_number"], errors="coerce").fillna(0).astype(int)
    df["match_number"] = pd.to_numeric(df["match_number"], errors="coerce").fillna(0).astype(int)
    df["match_level_sort"] = df["match_level"].apply(_sort_match_level)
    df["notes"] = df["notes"].fillna("")

    histories: List[TeamMatchHistory] = []
    for team_number in sorted(df["team_number"].unique()):
        team_df = df[df["team_number"] == team_number].copy()
        team_df = team_df.sort_values(["match_level_sort", "match_number"])

        matches: List[TeamMatchBreakdown] = []
        for _, row in team_df.iterrows():
            matches.append(
                TeamMatchBreakdown(
                    team_number=int(team_number),
                    match_level=str(row["match_level"]),
                    match_number=int(row["match_number"]),
                    autonomous_points=_round_stat(row["autonomous_points"]),
                    teleop_points=_round_stat(row["teleop_points"]),
                    endgame_points=_round_stat(row["endgame_points"]),
                    game_pieces=int(row["game_piece_count"])
                    if not pd.isna(row["game_piece_count"])
                    else 0,
                    total_points=_round_stat(row["total_points"]),
                    notes=str(row["notes"] or ""),
                )
            )

        histories.append(
            TeamMatchHistory(
                team_number=int(team_number),
                matches_played=len(matches),
                matches=matches,
            )
        )

    histories.sort(key=lambda entry: entry.team_number)
    return histories


