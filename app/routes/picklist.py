from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ConfigDict
from sqlmodel import SQLModel, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from auth.dependencies import get_current_user
from db.database import get_session
from models import PickList, PickListRank
from services.event import (
    get_active_event_key_for_user,
    get_event_or_404,
    require_lead_or_admin_membership,
)
from services.picklist import (
    fetch_picklist_generators,
    fetch_picklists_for_event,
    fetch_ranks_for_picklists,
    get_picklist_generator_model_for_year,
)
from services.season import get_season_by_year_or_404


router = APIRouter(
    prefix="/picklists",
    tags=["Pick Lists"],
)


class PickListRankPayload(SQLModel):
    rank: int
    team_number: int
    notes: Optional[str] = None
    dnp: bool = False


class PickListCreateRequest(SQLModel):
    title: str
    notes: Optional[str] = None
    favorited: Optional[bool] = False
    ranks: List[PickListRankPayload]


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


class PickListUpdateRequest(SQLModel):
    id: UUID
    title: Optional[str] = None
    notes: Optional[str] = None
    favorited: Optional[bool] = None
    ranks: Optional[List[PickListRankPayload]] = None


class PickListDeleteRequest(SQLModel):
    id: UUID


@router.get("/generators")
async def list_picklist_generators(
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
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

    seen_ranks = set()
    for entry in request.ranks:
        if entry.rank in seen_ranks:
            raise HTTPException(status_code=400, detail="Duplicate rank value provided.")
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


@router.post("/generators")
async def create_picklist_generator(
    request: PickListGeneratorCreateRequest,
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
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
