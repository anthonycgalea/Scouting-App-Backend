from fastapi import APIRouter, Body, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from auth.dependencies import get_current_user
from db.database import get_session
from typing import List, Optional

from models import DataValidation, MatchData

router = APIRouter(
    prefix="/scout",
    tags=["Scout"],
)

from services.scout import (
    DataValidationFilterRequest,
    DataValidationUpdateRequest,
    ScoutMatchFilterRequest,
    batch_submit_match,
    batch_update_data_validations,
    batch_update_match,
    get_already_scouted_matches,
    get_data_validations_for_active_event,
    submit_scouted_match,
)


@router.get("/dataValidation", response_model=List[DataValidation])
async def get_data_validation_records(
    filters: Optional[DataValidationFilterRequest] = Body(default=None),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_data_validations_for_active_event(session, user, filters)


@router.patch("/dataValidation", response_model=List[DataValidation])
async def update_data_validation_records(
    updates: List[DataValidationUpdateRequest],
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await batch_update_data_validations(session, user, updates)

@router.get("/matches")
async def get_scouted_matches(
    filters: Optional[ScoutMatchFilterRequest] = Body(default=None),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    return await get_already_scouted_matches(session, user, filters)

@router.post("/submit/batch")
async def submit_multiple_matches(
    matches: List[MatchData],
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    return await batch_submit_match(session, matches, user)

@router.post("/submit")
async def submit_single_match(
    match: MatchData,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    return await submit_scouted_match(session, match, user)

@router.put("/edit/batch")
async def edit_multiple_matches(
    matches: List[MatchData],
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    return await batch_update_match(session, matches, user)

@router.put("/edit")
async def edit_single_match(
    match: MatchData,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    return await submit_scouted_match(session, match, user)
