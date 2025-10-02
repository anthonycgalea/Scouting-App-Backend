"""Database model for storing robot image links for a team at an event."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class RobotEventImageLink(SQLModel, table=True):
    """A link to an image of a team's robot for a specific event."""

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    team_number: int = Field(foreign_key="teamrecord.team_number")
    event_key: str = Field(foreign_key="frcevent.event_key")
    image_url: str = Field(max_length=2048)
    description: Optional[str] = Field(default=None, max_length=255)
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
