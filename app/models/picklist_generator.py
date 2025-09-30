from datetime import datetime
from typing import Optional, Type
from uuid import UUID, uuid4

from sqlalchemy import event, select
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict


class PickListGenerator(SQLModel):
    """Base fields shared by all match data tables."""

    model_config = ConfigDict(extra="allow")
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    season: int = Field(foreign_key="season.id")
    organization_id: int = Field(foreign_key="organization.id")
    title: str = Field(default="Pick List Generator")
    notes: Optional[str] = Field(default="")
    timestamp: datetime = Field(default_factory=datetime.now)
    favorited: bool = Field(default=False)