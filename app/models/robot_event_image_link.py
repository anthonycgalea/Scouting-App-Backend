from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
import uuid


class RobotEventImageLink(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, index=True)
    team_number: int = Field(foreign_key="teamrecord.team_number")
    event_key: str = Field(foreign_key="frcevent.event_key")
    image_url: str = Field(max_length=2048)
    description: Optional[str] = Field(default=None, max_length=255)
    uploaded_at: datetime = Field(default_factory=datetime.now())