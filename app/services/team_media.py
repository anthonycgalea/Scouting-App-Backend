"""Service layer for managing team robot media uploads."""

from __future__ import annotations

import asyncio
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import RobotEventImageLink
from app.services.aws import get_s3_client, get_team_images_bucket
from app.services.event import (
    get_active_event_key_for_user,
    get_event_or_404,
    get_match_or_404,
)
from app.services.team import get_team_or_404
from sqlmodel import SQLModel

ALLOWED_IMAGE_EXTENSIONS: Iterable[str] = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
ALLOWED_IMAGE_CONTENT_TYPES: Iterable[str] = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/webp",
}
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class RobotEventImageLinkResponse(SQLModel):
    """Response DTO for robot event image link records."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_number: int
    event_key: str
    image_url: str
    description: Optional[str]
    uploaded_at: datetime


class EventTeamImagesResponse(BaseModel):
    """Response DTO for grouped team robot images at an event."""

    teamNumber: int
    images: list[str]


async def _ensure_team_and_event(session: AsyncSession, team_number: int, event_key: str) -> None:
    """Validate that the requested team and event exist."""

    await get_team_or_404(session, team_number)
    await get_event_or_404(session, event_key)


def _validate_upload(upload: UploadFile) -> tuple[str, str]:
    """Validate the uploaded file and return its suffix and content type."""

    if not upload.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must include a filename.",
        )

    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported image file type.",
        )

    content_type = upload.content_type or ""
    if content_type.lower() not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported image content type.",
        )

    return suffix, content_type


async def _read_upload(upload: UploadFile) -> BytesIO:
    """Read the upload into memory enforcing a maximum size constraint."""

    contents = await upload.read()
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file was empty.",
        )

    if len(contents) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Uploaded file exceeds the 10MB limit.",
        )

    file_buffer = BytesIO(contents)
    file_buffer.seek(0)
    return file_buffer


async def upload_team_image(
    session: AsyncSession,
    team_number: int,
    upload: UploadFile,
    description: Optional[str],
    user: dict,
) -> RobotEventImageLinkResponse:
    """Upload an image for a team's robot and persist its metadata."""

    event_key = await get_active_event_key_for_user(session, user)

    await _ensure_team_and_event(session, team_number, event_key)

    suffix, content_type = _validate_upload(upload)
    file_buffer = await _read_upload(upload)

    object_key = f"{event_key}/{team_number}/{uuid4()}{suffix}"
    bucket = get_team_images_bucket()
    s3_client = get_s3_client()

    extra_args = {"ContentType": content_type}

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: s3_client.upload_fileobj(
            file_buffer,
            bucket,
            object_key,
            ExtraArgs=extra_args,
        ),
    )

    image_url = f"https://{bucket}.s3.amazonaws.com/{object_key}"

    record = RobotEventImageLink(
        team_number=team_number,
        event_key=event_key,
        image_url=image_url,
        description=description,
        uploaded_at=datetime.utcnow(),
    )

    session.add(record)
    await session.commit()
    await session.refresh(record)

    return RobotEventImageLinkResponse.model_validate(record)


async def list_team_images(
    session: AsyncSession,
    team_number: int,
    user: dict,
) -> list[RobotEventImageLinkResponse]:
    """Return the stored robot images for a team at the user's active event."""

    event_key = await get_active_event_key_for_user(session, user)

    await _ensure_team_and_event(session, team_number, event_key)

    statement = (
        select(RobotEventImageLink)
        .where(
            RobotEventImageLink.team_number == team_number,
            RobotEventImageLink.event_key == event_key,
        )
        .order_by(RobotEventImageLink.uploaded_at.desc())
    )
    result = await session.execute(statement)
    records = result.scalars().all()
    return [RobotEventImageLinkResponse.model_validate(record) for record in records]


async def list_event_team_images(
    session: AsyncSession,
    user: dict,
) -> list[EventTeamImagesResponse]:
    """Return robot images for every team at the user's active event."""

    event_key = await get_active_event_key_for_user(session, user)

    statement = (
        select(
            RobotEventImageLink.team_number,
            RobotEventImageLink.image_url,
        )
        .where(RobotEventImageLink.event_key == event_key)
        .order_by(
            RobotEventImageLink.team_number.asc(),
            RobotEventImageLink.uploaded_at.desc(),
        )
    )

    result = await session.execute(statement)

    grouped_images: dict[int, list[str]] = {}
    for team_number, image_url in result.all():
        grouped_images.setdefault(team_number, []).append(image_url)

    return [
        EventTeamImagesResponse(teamNumber=team_number, images=images)
        for team_number, images in grouped_images.items()
    ]


async def list_match_team_images(
    session: AsyncSession,
    user: dict,
    match_level: str,
    match_number: int,
) -> list[EventTeamImagesResponse]:
    """Return robot images for every team competing in a specific match."""

    event_key = await get_active_event_key_for_user(session, user)

    match = await get_match_or_404(session, event_key, match_number, match_level)

    team_order: list[int] = []
    seen: set[int] = set()
    for team_number in (
        match.red1_id,
        match.red2_id,
        match.red3_id,
        match.blue1_id,
        match.blue2_id,
        match.blue3_id,
    ):
        if team_number not in seen:
            seen.add(team_number)
            team_order.append(team_number)

    if not team_order:
        return []

    statement = (
        select(
            RobotEventImageLink.team_number,
            RobotEventImageLink.image_url,
        )
        .where(
            RobotEventImageLink.event_key == event_key,
            RobotEventImageLink.team_number.in_(team_order),
        )
        .order_by(
            RobotEventImageLink.team_number.asc(),
            RobotEventImageLink.uploaded_at.desc(),
        )
    )

    result = await session.execute(statement)

    grouped_images: dict[int, list[str]] = {team_number: [] for team_number in team_order}
    for team_number, image_url in result.all():
        grouped_images.setdefault(team_number, []).append(image_url)

    return [
        EventTeamImagesResponse(
            teamNumber=team_number,
            images=grouped_images.get(team_number, []),
        )
        for team_number in team_order
    ]
