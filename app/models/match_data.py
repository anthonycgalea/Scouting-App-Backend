from enum import Enum
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID, uuid4

class MatchData(SQLModel):
    season: int = Field(foreign_key="season.id")
    team_number: int = Field(
        foreign_key="teamrecord.team_number", 
        primary_key=True, 
        max_length=10
    )
    event_key: str = Field(
        foreign_key="frcevent.event_key", 
        primary_key=True, 
        max_length=15
    )
    match_number: int = Field(primary_key=True)
    match_level: str = Field(primary_key=True, max_length=50)
    user_id: UUID = Field(
        primary_key=True,
        foreign_key="users.id"
    )
    organization_id: int = Field(foreign_key="organization.id")
    timestamp: datetime = Field(default_factory=datetime.now())
    notes: str