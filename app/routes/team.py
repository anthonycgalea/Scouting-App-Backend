from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlmodel.ext.asyncio.session import AsyncSession

from auth.dependencies import get_current_user
from db.database import get_session
from services.team import (
    get_match_data_for_team_at_active_event,
    get_team_or_404,
)
from services.team_media import (
    RobotEventImageLinkResponse,
    list_team_images,
    upload_team_image,
)

router = APIRouter(
    prefix="/teams",
    tags=["Team"],
)


@router.get("/{teamNumber}/info")
async def get_team_info(teamNumber: int, session: AsyncSession = Depends(get_session)):
    return await get_team_or_404(session, teamNumber)


@router.get("/{teamNumber}/matchData")
async def get_team_match_data(
    teamNumber: int,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await get_match_data_for_team_at_active_event(session, teamNumber, user)


@router.post(
    "/{teamNumber}/images",
    response_model=RobotEventImageLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_team_image_endpoint(
    teamNumber: int,
    event_key: str = Form(...),
    file: UploadFile = File(...),
    description: str | None = Form(None),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await upload_team_image(
        session=session,
        team_number=teamNumber,
        event_key=event_key,
        upload=file,
        description=description,
        user=user,
    )


@router.get(
    "/{teamNumber}/images",
    response_model=list[RobotEventImageLinkResponse],
)
async def list_team_images_endpoint(
    teamNumber: int,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await list_team_images(session, teamNumber, user)
