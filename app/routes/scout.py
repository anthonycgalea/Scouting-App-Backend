from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from auth.dependencies import get_current_user
from db.database import get_session
from typing import List, Optional
from uuid import UUID

from sqlmodel import select

from models import DataValidation, MatchData, Season, ValidationStatus
from services.event import MATCH_DATA_MODELS_BY_YEAR

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
    update_scouted_match,
    update_tba_match_data_for_pending_alliances,
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


@router.put("/dataValidation", response_model=DataValidation)
async def mark_match_data_valid(
    match: MatchData,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    match_payload = match.model_dump()
    requested_notes = match_payload.get("notes")

    season = await session.get(Season, match.season)
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found for provided match data")

    match_model = MATCH_DATA_MODELS_BY_YEAR.get(season.year)
    if match_model is None:
        raise HTTPException(status_code=404, detail="Match data is not available for this event")

    user_id: UUID = match.user_id if isinstance(match.user_id, UUID) else UUID(str(match.user_id))

    statement = select(match_model).where(
        match_model.event_key == match.event_key,
        match_model.match_number == match.match_number,
        match_model.match_level == match.match_level,
        match_model.team_number == match.team_number,
        match_model.user_id == user_id,
        match_model.organization_id == match.organization_id,
    )

    result = await session.execute(statement)
    stored_match = result.scalars().first()

    if stored_match is None:
        raise HTTPException(status_code=404, detail="Match data not found for the provided identifiers")

    dummy_payload = {**match_payload, "notes": stored_match.notes or ""}

    dummy_match = match_model(**dummy_payload)

    await update_scouted_match(session, dummy_match, user)

    validation_stmt = select(DataValidation).where(
        DataValidation.event_key == match.event_key,
        DataValidation.match_number == match.match_number,
        DataValidation.match_level == match.match_level,
        DataValidation.team_number == match.team_number,
        DataValidation.user_id == user_id,
        DataValidation.organization_id == match.organization_id,
    )

    validation_result = await session.execute(validation_stmt)
    validation = validation_result.scalars().first()

    if validation is None:
        raise HTTPException(status_code=404, detail="Data validation record not found for this match")

    validation.validation_status = ValidationStatus.VALID
    if "notes" in match_payload:
        validation.notes = (requested_notes or "") if requested_notes is not None else ""

    session.add(validation)
    await session.commit()
    await session.refresh(validation)

    return validation


@router.post("/data/tbaUpdate")
async def update_tba_data(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await update_tba_match_data_for_pending_alliances(session, user)

@router.post("/matches")
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
