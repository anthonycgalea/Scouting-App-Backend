from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from uuid import UUID, uuid4
from .picklist_generator import PickListGenerator
from datetime import datetime

class PickList(SQLModel, table=True):
    __tablename__ = "picklist"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    season: int = Field(foreign_key="season.id")
    organization_id: int = Field(foreign_key="organization.id")
    event_key: int = Field(foreign_key="frcevent.event_key")
    title: str = Field(default="Pick List")
    notes: Optional[str] = Field(default="")
    created: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)
    favorited: bool = Field(default=False)