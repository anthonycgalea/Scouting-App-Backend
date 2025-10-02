"""Service layer for managing team robot media uploads."""

from __future__ import annotations

import asyncio
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from pydantic import ConfigDict
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models import RobotEventImageLink
from services.aws import get_s3_client, get_team_images_bucket
from services.event import get_active_event_key_for_user, get_event_or_404
from services.team import get_team_or_404
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

    extra_args = {"ACL": "public-read", "ContentType": content_type}

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
