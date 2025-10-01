from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence, Type
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import (
    PickList,
    PickListGenerator,
    PickListGenerator2025,
    PickListRank,
)


PICKLIST_GENERATOR_MODELS_BY_YEAR: Dict[int, Type[PickListGenerator]] = {
    2025: PickListGenerator2025,
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
    season: int,
) -> List[PickListGenerator]:
    generator_model = get_picklist_generator_model_for_year(season)
    statement = select(generator_model).where(
        generator_model.organization_id == organization_id,
        generator_model.season == season,
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
