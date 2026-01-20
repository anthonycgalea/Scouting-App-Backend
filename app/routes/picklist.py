from __future__ import annotations

from datetime import datetime
from functools import reduce
from typing import Any, Dict, List, Optional, Type
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ConfigDict
from sqlmodel import Field, SQLModel, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.database import get_session
from app.models import PickList, PickListGenerator, PickListRank
from app.services.event import (
    get_active_event_key_for_user,
    get_event_or_404,
    require_lead_or_admin_membership,
)
from app.services.picklist import (
    PICKLIST_GENERATOR_MODELS_BY_YEAR,
    fetch_picklist_generators,
    fetch_picklists_for_event,
    fetch_ranks_for_picklists,
    generate_picklist_ranks_from_generator,
    get_picklist_generator_by_id,
    get_picklist_generator_model_for_year,
)
from app.services.season import get_season_by_year_or_404


router = APIRouter(
    prefix="/picklists",
    tags=["Pick Lists"],
)

picklist_generator_response_types: List[Type[PickListGenerator]] = []

for generator_model in PICKLIST_GENERATOR_MODELS_BY_YEAR.values():
    if generator_model not in picklist_generator_response_types:
        picklist_generator_response_types.append(generator_model)

if PickListGenerator not in picklist_generator_response_types:
    picklist_generator_response_types.append(PickListGenerator)

PickListGeneratorResponse = reduce(
    lambda accumulated, next_model: accumulated | next_model,
    picklist_generator_response_types[1:],
    picklist_generator_response_types[0],
)


class PickListRankPayload(SQLModel):
    rank: int
    team_number: int
    notes: Optional[str] = None
    dnp: bool = False


class PickListCreateRequest(SQLModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    notes: Optional[str] = None
    favorited: Optional[bool] = False
    generator_id: Optional[UUID] = Field(default=None, alias="generatorId")
    ranks: List[PickListRankPayload] = Field(default_factory=list)


class PickListRankResponse(PickListRankPayload):
    pass


class PickListResponse(SQLModel):
    id: UUID
    season: int
    organization_id: int
    event_key: str
    title: str
    notes: Optional[str]
    created: datetime
    last_updated: datetime
    favorited: bool
    ranks: List[PickListRankResponse]


class PickListGeneratorCreateRequest(SQLModel):
    model_config = ConfigDict(extra="allow")

    title: str
    notes: str
    favorited: bool


class PickListGeneratorUpdateRequest(SQLModel):
    model_config = ConfigDict(extra="allow")

    id: UUID
    title: Optional[str] = None
    notes: Optional[str] = None
    favorited: Optional[bool] = None


class PickListUpdateRequest(SQLModel):
    id: UUID
    title: Optional[str] = None
    notes: Optional[str] = None
    favorited: Optional[bool] = None
    ranks: Optional[List[PickListRankPayload]] = None


class PickListDeleteRequest(SQLModel):
    id: UUID


class PickListGeneratorDeleteRequest(SQLModel):
    id: UUID


@router.get("/generators", response_model=List[PickListGeneratorResponse])
async def list_picklist_generators(
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[PickListGeneratorResponse]:
    membership = await require_lead_or_admin_membership(session, user)
    event_key = await get_active_event_key_for_user(session, user)
    event = await get_event_or_404(session, event_key)
    season = await get_season_by_year_or_404(session, event.year)

    generators = await fetch_picklist_generators(
        session,
        membership.organization_id,
        event.year,
        season.id,
    )

    return [generator.model_dump() for generator in generators]


@router.get("")
async def list_picklists(
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[PickListResponse]:
    membership = await require_lead_or_admin_membership(session, user)
    event_key = await get_active_event_key_for_user(session, user)

    picklists = await fetch_picklists_for_event(
        session,
        membership.organization_id,
        event_key,
    )

    ranks_by_picklist = await fetch_ranks_for_picklists(
        session,
        [picklist.id for picklist in picklists],
    )

    responses: List[PickListResponse] = []
    for picklist in picklists:
        ranks = [
            PickListRankResponse(**rank.model_dump(exclude={"picklist_id"}))
            for rank in ranks_by_picklist.get(picklist.id, [])
        ]
        picklist_data = PickListResponse(
            **picklist.model_dump(),
            ranks=ranks,
        )
        responses.append(picklist_data)

    return responses


@router.post("")
async def create_picklist(
    request: PickListCreateRequest,
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(get_current_user),
) -> PickListResponse:
    membership = await require_lead_or_admin_membership(session, user)
    event_key = await get_active_event_key_for_user(session, user)
    event = await get_event_or_404(session, event_key)
    season = await get_season_by_year_or_404(session, event.year)

    generated_rankings: List[int] = []
    if request.generator_id is not None:
        generator = await get_picklist_generator_by_id(
            session=session,
            generator_id=request.generator_id,
            organization_id=membership.organization_id,
            season_id=season.id,
            season_year=event.year,
        )
        generated_rankings = await generate_picklist_ranks_from_generator(
            session=session,
            user=user,
            generator=generator,
        )
    else:
        seen_ranks = set()
        for entry in request.ranks:
            if entry.rank in seen_ranks:
                raise HTTPException(
                    status_code=400, detail="Duplicate rank value provided."
                )
            seen_ranks.add(entry.rank)

    timestamp = datetime.now()
    picklist = PickList(
        season=season.id,
        organization_id=membership.organization_id,
        event_key=event_key,
        title=request.title,
        notes=request.notes or "",
        favorited=request.favorited if request.favorited is not None else False,
        created=timestamp,
        last_updated=timestamp,
    )
    session.add(picklist)
    await session.flush()

    if generated_rankings:
        for index, team_number in enumerate(generated_rankings, start=1):
            rank_entry = PickListRank(
                picklist_id=picklist.id,
                rank=index,
                team_number=team_number,
                notes="",
                dnp=False,
            )
            session.add(rank_entry)
    else:
        for rank in request.ranks:
            rank_entry = PickListRank(
                picklist_id=picklist.id,
                rank=rank.rank,
                team_number=rank.team_number,
                notes=rank.notes or "",
                dnp=rank.dnp,
            )
            session.add(rank_entry)

    await session.commit()
    await session.refresh(picklist)

    ranks = await fetch_ranks_for_picklists(session, [picklist.id])
    rank_responses = [
        PickListRankResponse(**rank.model_dump(exclude={"picklist_id"}))
        for rank in ranks.get(picklist.id, [])
    ]

    return PickListResponse(
        **picklist.model_dump(),
        ranks=rank_responses,
    )


@router.delete("")
async def delete_picklist(
    request: PickListDeleteRequest,
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, bool]:
    membership = await require_lead_or_admin_membership(session, user)
    event_key = await get_active_event_key_for_user(session, user)

    picklist = await session.get(PickList, request.id)

    if (
        picklist is None
        or picklist.organization_id != membership.organization_id
        or picklist.event_key != event_key
    ):
        raise HTTPException(status_code=404, detail="Pick list not found.")

    await session.execute(
        delete(PickListRank).where(PickListRank.picklist_id == picklist.id)
    )
    await session.delete(picklist)

    await session.commit()

    return {"success": True}


@router.patch("")
async def update_picklists(
    requests: List[PickListUpdateRequest],
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[PickListResponse]:
    if not requests:
        return []

    membership = await require_lead_or_admin_membership(session, user)
    event_key = await get_active_event_key_for_user(session, user)

    updated_picklists: List[PickList] = []

    for request in requests:
        picklist = await session.get(PickList, request.id)
        if (
            picklist is None
            or picklist.organization_id != membership.organization_id
            or picklist.event_key != event_key
        ):
            raise HTTPException(status_code=404, detail="Pick list not found.")

        if request.title is not None:
            picklist.title = request.title

        if request.notes is not None:
            picklist.notes = request.notes

        if request.favorited is not None:
            picklist.favorited = request.favorited

        if request.ranks is not None:
            seen_ranks = set()
            for rank in request.ranks:
                if rank.rank in seen_ranks:
                    raise HTTPException(
                        status_code=400,
                        detail="Duplicate rank value provided.",
                    )
                seen_ranks.add(rank.rank)

            await session.execute(
                delete(PickListRank).where(PickListRank.picklist_id == picklist.id)
            )

            for rank in request.ranks:
                rank_entry = PickListRank(
                    picklist_id=picklist.id,
                    rank=rank.rank,
                    team_number=rank.team_number,
                    notes=rank.notes or "",
                    dnp=rank.dnp,
                )
                session.add(rank_entry)

        picklist.last_updated = datetime.now()
        updated_picklists.append(picklist)


    picklist_ids = [picklist.id for picklist in updated_picklists]
    await session.commit()
    ranks_by_picklist = await fetch_ranks_for_picklists(session, picklist_ids)

    responses: List[PickListResponse] = []
    for picklist in updated_picklists:
        await session.refresh(picklist)
        ranks = [
            PickListRankResponse(**rank.model_dump(exclude={"picklist_id"}))
            for rank in ranks_by_picklist.get(picklist.id, [])
        ]
        responses.append(
            PickListResponse(
                **picklist.model_dump(),
                ranks=ranks,
            )
        )

    return responses


@router.post("/generators", response_model=PickListGeneratorResponse)
async def create_picklist_generator(
    request: PickListGeneratorCreateRequest,
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(get_current_user),
) -> PickListGeneratorResponse:
    membership = await require_lead_or_admin_membership(session, user)
    event_key = await get_active_event_key_for_user(session, user)
    event = await get_event_or_404(session, event_key)
    season = await get_season_by_year_or_404(session, event.year)

    generator_model = get_picklist_generator_model_for_year(event.year)

    payload = request.model_dump()
    base_fields = {
        "title": payload.pop("title"),
        "notes": payload.pop("notes"),
        "favorited": payload.pop("favorited"),
    }

    generator = generator_model(
        season=season.id,
        organization_id=membership.organization_id,
        **base_fields,
        **payload,
    )
    session.add(generator)
    await session.commit()
    await session.refresh(generator)

    return generator.model_dump()


@router.delete("/generators")
async def delete_picklist_generator(
    request: PickListGeneratorDeleteRequest,
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, bool]:
    membership = await require_lead_or_admin_membership(session, user)
    event_key = await get_active_event_key_for_user(session, user)
    event = await get_event_or_404(session, event_key)
    season = await get_season_by_year_or_404(session, event.year)

    generator_model = get_picklist_generator_model_for_year(event.year)
    generator = await session.get(generator_model, request.id)

    if (
        generator is None
        or generator.organization_id != membership.organization_id
        or generator.season != season.id
    ):
        raise HTTPException(status_code=404, detail="Pick list generator not found.")

    await session.delete(generator)
    await session.commit()

    return {"success": True}


@router.patch("/generators", response_model=PickListGeneratorResponse)
async def update_picklist_generator(
    request: PickListGeneratorUpdateRequest,
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(get_current_user),
) -> PickListGeneratorResponse:
    membership = await require_lead_or_admin_membership(session, user)
    event_key = await get_active_event_key_for_user(session, user)
    event = await get_event_or_404(session, event_key)
    season = await get_season_by_year_or_404(session, event.year)

    generator_model = get_picklist_generator_model_for_year(event.year)

    generator = await session.get(generator_model, request.id)

    if (
        generator is None
        or generator.organization_id != membership.organization_id
        or generator.season != season.id
    ):
        raise HTTPException(status_code=404, detail="Pick list generator not found.")

    payload = request.model_dump(exclude_none=True)
    for field in ("id", "season", "organization_id", "timestamp"):
        payload.pop(field, None)

    for field, value in payload.items():
        setattr(generator, field, value)

    generator.timestamp = datetime.now()

    await session.commit()
    await session.refresh(generator)

    return generator.model_dump()
