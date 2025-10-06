from functools import reduce
from typing import Any, Dict, List, Optional, Type
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from auth.dependencies import get_current_user
from db.database import get_session

from models import DataValidation, MatchData, PitScout, Season, SuperScoutData, ValidationStatus
from services.event import MATCH_DATA_MODELS_BY_YEAR
from services.scout import PIT_SCOUT_MODELS_BY_YEAR

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
    create_pit_scout_record,
    delete_pit_scout_record,
    get_already_scouted_matches,
    get_prescout_records,
    get_superscout_field_options,
    get_superscout_records,
    get_data_validations_for_active_event,
    get_pit_scout_records,
    PitScoutDeleteRequest,
    PRESCOUT_MODELS_BY_YEAR,
    SUPERSCOUT_MODELS_BY_YEAR,
    submit_scouted_match,
    submit_prescout_record,
    submit_superscout_record,
    update_scouted_match,
    update_pit_scout_record,
    update_tba_match_data_for_pending_alliances,
)


class SuperScoutFieldOption(BaseModel):
    key: str
    label: str


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

    stored_payload = stored_match.model_dump()

    merged_payload = {**stored_payload, **{key: value for key, value in match_payload.items() if key != "notes"}}

    if "notes" in match_payload:
        merged_payload["notes"] = (requested_notes or "") if requested_notes is not None else ""
    else:
        merged_payload["notes"] = stored_payload.get("notes") or ""

    dummy_match = match_model(**merged_payload)

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


pit_scout_response_types: List[Type[PitScout]] = []

for pit_model in PIT_SCOUT_MODELS_BY_YEAR.values():
    if pit_model not in pit_scout_response_types:
        pit_scout_response_types.append(pit_model)

if PitScout not in pit_scout_response_types:
    pit_scout_response_types.append(PitScout)

PitScoutResponse = reduce(
    lambda accumulated, next_model: accumulated | next_model,
    pit_scout_response_types[1:],
    pit_scout_response_types[0],
)


prescout_response_types: List[Type[MatchData]] = []

for prescout_model in PRESCOUT_MODELS_BY_YEAR.values():
    if prescout_model not in prescout_response_types:
        prescout_response_types.append(prescout_model)

if MatchData not in prescout_response_types:
    prescout_response_types.append(MatchData)

PrescoutResponse = reduce(
    lambda accumulated, next_model: accumulated | next_model,
    prescout_response_types[1:],
    prescout_response_types[0],
)


superscout_response_types: List[Type[SuperScoutData]] = []

for superscout_model in SUPERSCOUT_MODELS_BY_YEAR.values():
    if superscout_model not in superscout_response_types:
        superscout_response_types.append(superscout_model)

if SuperScoutData not in superscout_response_types:
    superscout_response_types.append(SuperScoutData)

SuperScoutResponse = reduce(
    lambda accumulated, next_model: accumulated | next_model,
    superscout_response_types[1:],
    superscout_response_types[0],
)


@router.get("/pit", response_model=List[PitScoutResponse])
async def list_pit_scout_records(
    team_number: Optional[int] = Query(default=None, alias="teamNumber"),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_pit_scout_records(session, user, team_number=team_number)


@router.post("/pit", response_model=PitScoutResponse, status_code=201)
async def create_pit_scout_entry(
    pit: Dict[str, Any] = Body(...),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await create_pit_scout_record(session, pit, user)


@router.patch("/pit", response_model=PitScoutResponse)
async def update_pit_scout_entry(
    pit: Dict[str, Any] = Body(...),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await update_pit_scout_record(session, pit, user)


@router.delete("/pit", status_code=204)
async def delete_pit_scout_entry(
    request: PitScoutDeleteRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await delete_pit_scout_record(session, request, user)


@router.get("/prescout", response_model=List[PrescoutResponse])
async def list_prescout_records(
    team_number: Optional[int] = Query(default=None, alias="teamNumber"),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_prescout_records(session, user, team_number=team_number)


@router.post("/prescout", response_model=PrescoutResponse, status_code=201)
async def create_prescout_entry(
    prescout: MatchData,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await submit_prescout_record(session, prescout, user)


@router.get("/superscout", response_model=List[SuperScoutResponse])
async def list_superscout_records(
    team_number: Optional[int] = Query(default=None, alias="teamNumber"),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_superscout_records(session, user, team_number=team_number)


@router.get("/superscout/fields", response_model=List[SuperScoutFieldOption])
async def list_superscout_field_options(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_superscout_field_options(session, user)


@router.post("/superscout", response_model=SuperScoutResponse, status_code=201)
async def create_superscout_entry(
    superscout: SuperScoutData,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await submit_superscout_record(session, superscout, user)


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
