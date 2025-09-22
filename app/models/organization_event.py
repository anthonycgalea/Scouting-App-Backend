from sqlmodel import SQLModel, Field, Relationship
from uuid import UUID, uuid4
from typing import Optional

class OrganizationEvent(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id")
    event_key: str = Field(foreign_key="frcevent.event_key")
    public_data: bool = Field(default=False)  # True if data is public
    active: bool = Field(default=True) #True if event is able to have data submitted/edited
