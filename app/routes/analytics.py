from typing import List

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from auth.dependencies import get_current_user
from db.database import get_session
from services.analytics.event_summary import (
    EventTeamZScoreResponse,
    TeamEventDetailedSummary,
    TeamEventSummary,
    TeamMatchHistory,
    get_team_event_detailed_summary,
    get_team_event_match_history,
    get_team_event_summary,
    get_team_event_z_scores,
)

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
)


@router.get("/eventSummary/teams", response_model=List[TeamEventSummary])
async def summarize_event_by_team(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_team_event_summary(session, user)


@router.get(
    "/event/teams/detailed",
    response_model=List[TeamEventDetailedSummary],
)
async def summarize_event_by_team_detailed(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_team_event_detailed_summary(session, user)


@router.get(
    "/event/teams/matches",
    response_model=List[TeamMatchHistory],
)
async def get_event_team_match_history(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_team_event_match_history(session, user)


@router.get(
    "/event/teams/zScores",
    response_model=EventTeamZScoreResponse,
)
async def get_event_team_z_scores(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_team_event_z_scores(session, user)
