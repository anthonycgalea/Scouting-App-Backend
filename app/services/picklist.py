from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Sequence, Type
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    PickList,
    PickListGenerator,
    PickListGenerator2025,
    PickListGenerator2026,
    PickListRank,
)
from app.services.analytics.event_summary import get_team_event_z_scores


PICKLIST_GENERATOR_MODELS_BY_YEAR: Dict[int, Type[PickListGenerator]] = {
    2025: PickListGenerator2025,
    2026: PickListGenerator2026,
}


GENERATOR_FIELD_TO_Z_SCORE: Dict[str, str] = {
    "al4c": "autonomous_level_4_coral_z",
    "al3c": "autonomous_level_3_coral_z",
    "al2c": "autonomous_level_2_coral_z",
    "al1c": "autonomous_level_1_coral_z",
    "autonomous_coral": "autonomous_coral_z",
    "autonomous_algae": "autonomous_algae_z",
    "autonomous_points": "autonomous_points_z",
    "tl4c": "teleop_level_4_coral_z",
    "tl3c": "teleop_level_3_coral_z",
    "tl2c": "teleop_level_2_coral_z",
    "tl1c": "teleop_level_1_coral_z",
    "teleop_coral": "teleop_coral_z",
    "teleop_algae": "teleop_algae_z",
    "teleop_points": "teleop_points_z",
    "aNet": "autonomous_net_z",
    "tNet": "teleop_net_z",
    "aProcessor": "autonomous_processor_z",
    "tProcessor": "teleop_processor_z",
    "endgame_points": "endgame_points_z",
    "total_coral": "total_coral_z",
    "total_algae": "total_algae_z",
    "total_game_pieces": "total_game_pieces_z",
    "total_points": "total_points_z",
}


def get_picklist_generator_model_for_year(year: int) -> Type[PickListGenerator]:
    try:
        return PICKLIST_GENERATOR_MODELS_BY_YEAR[year]
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Pick list generators are not available for the {year} season.",
        ) from exc


async def fetch_picklist_generators(
    session: AsyncSession,
    organization_id: int,
    season_year: int,
    season_id: int,
) -> List[PickListGenerator]:
    generator_model = get_picklist_generator_model_for_year(season_year)
    statement = select(generator_model).where(
        generator_model.organization_id == organization_id,
        generator_model.season == season_id,
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def fetch_picklists_for_event(
    session: AsyncSession,
    organization_id: int,
    event_key: str,
) -> List[PickList]:
    statement = select(PickList).where(
        PickList.organization_id == organization_id,
        PickList.event_key == event_key,
    ).order_by(PickList.favorited.desc(), PickList.created.desc())
    result = await session.execute(statement)
    return list(result.scalars().all())


async def fetch_ranks_for_picklists(
    session: AsyncSession,
    picklist_ids: Sequence[UUID],
) -> Dict[UUID, List[PickListRank]]:
    if not picklist_ids:
        return {}

    statement = (
        select(PickListRank)
        .where(PickListRank.picklist_id.in_(picklist_ids))
        .order_by(PickListRank.picklist_id, PickListRank.rank)
    )
    result = await session.execute(statement)

    ranks_by_picklist: Dict[UUID, List[PickListRank]] = defaultdict(list)
    for rank in result.scalars().all():
        ranks_by_picklist[rank.picklist_id].append(rank)

    return ranks_by_picklist


async def get_picklist_generator_by_id(
    session: AsyncSession,
    generator_id: UUID,
    organization_id: int,
    season_id: int,
    season_year: int,
) -> PickListGenerator:
    generator_model = get_picklist_generator_model_for_year(season_year)
    generator = await session.get(generator_model, generator_id)

    if generator is None:
        raise HTTPException(status_code=404, detail="Pick list generator not found")

    if generator.organization_id != organization_id or generator.season != season_id:
        raise HTTPException(status_code=403, detail="Access to this generator is denied")

    return generator


async def generate_picklist_ranks_from_generator(
    session: AsyncSession,
    user: Dict[str, Any],
    generator: PickListGenerator,
) -> List[int]:
    z_scores = await get_team_event_z_scores(session, user)
    teams = z_scores.teams

    if not teams:
        return []

    weighted_scores: List[tuple[int, float]] = []
    for team in teams:
        total_score = 0.0
        for field, z_column in GENERATOR_FIELD_TO_Z_SCORE.items():
            weight = getattr(generator, field, 0.0)
            if not weight:
                continue
            z_value = getattr(team, z_column, 0.0)
            total_score += weight * z_value

        weighted_scores.append((team.team_number, total_score))

    weighted_scores.sort(key=lambda item: (-item[1], item[0]))
    return [team_number for team_number, _ in weighted_scores]
