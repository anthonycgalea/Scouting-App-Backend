from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from app.auth.dependencies import get_current_user
from app.db.database import get_session
from typing import Any, Dict, List, Optional, Union

from app.models import Organization, FRCEvent

router = APIRouter(
    prefix="/event",
    tags=["Event"],
)

from app.services.event import *
from app.services.match_prediction import (
    get_match_prediction_for_user_organization,
    list_match_predictions_for_event,
    simulate_match_prediction,
)
from app.services.team_media import (
    EventTeamImagesResponse,
    list_event_team_images,
    list_match_team_images,
)

@router.get("/match/{matchLevel}/{matchNumber}", tags=["Scout"])
async def get_single_match(
    matchNumber: int,
    matchLevel: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> MatchScheduleResponse:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_match_or_404(session, event_code, matchNumber, matchLevel)


@router.get("/match/{matchLevel}/{matchNumber}/preview", tags=["Scout"])
async def get_match_preview_endpoint(
    matchNumber: int,
    matchLevel: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> MatchPreviewResponse:
    return await get_match_preview(session, user, matchNumber, matchLevel)


@router.get("/match/{matchLevel}/{matchNumber}/simulation", tags=["Scout"])
async def get_match_simulation(
    matchNumber: int,
    matchLevel: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    prediction = await get_match_prediction_for_user_organization(
        session, user, matchLevel, matchNumber
    )
    return prediction


@router.post("/match/{matchLevel}/{matchNumber}/simulation", tags=["Scout"])
async def run_match_simulation(
    matchNumber: int,
    matchLevel: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    event_code = await get_active_event_key_for_user(session, user)
    return await simulate_match_prediction(session, event_code, matchLevel, matchNumber)


@router.get("/matches/simulation", tags=["Scout"])
async def list_match_simulations(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    return await list_match_predictions_for_event(session, user)


@router.get("/matches")
async def get_match_schedule(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> List[MatchScheduleResponse]:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_match_schedule_or_404(session, event_code)


@router.post(
    "/tbaMatchData",
    response_model=Union[Dict[str, Any], List[Dict[str, Any]]],
)
async def get_tba_match_data(
    request: Optional[TBAMatchDataRequest] = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    return await fetch_tba_match_data(session, user, request)


@router.get("/tbaMatchData", response_model=List[Dict[str, Any]])
async def list_tba_match_data(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    return await list_tba_match_data_for_event(session, user)

@router.get("/organizations")
async def get_event_organizations(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> List[Organization]:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_public_organizations_for_event(session, event_code)


@router.get("/teams")
async def get_team_list(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> List[TeamRecordResponse]:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_team_list_or_404(session, event_code)


@router.get("/rankings")
async def get_event_rankings(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> List[EventRankingResponse]:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_event_rankings_or_404(session, event_code)


@router.post("/getRankings")
async def update_event_rankings(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> Dict[str, Any]:
    return await update_event_rankings_from_tba(session, user)


@router.get("/info")
async def get_event_info(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> FRCEvent:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_event_or_404(session, event_code)


@router.get("/images", response_model=list[EventTeamImagesResponse])
async def list_event_images_endpoint(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    return await list_event_team_images(session, user)


@router.get(
    "/match/{matchLevel}/{matchNumber}/images",
    response_model=list[EventTeamImagesResponse],
)
async def list_match_images_endpoint(
    matchLevel: str,
    matchNumber: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    return await list_match_team_images(session, user, matchLevel, matchNumber)


@router.get("s/{year}")
async def get_event_list(year: int, session: AsyncSession = Depends(get_session)) -> List[EventResponse]:
    return await get_event_list_or_404(session, year)
