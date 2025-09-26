from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from enum import Enum
from uuid import UUID

class ValidationStatus(str, Enum):
    PENDING = "PENDING"
    NEEDS_REVIEW = "NEEDS REVIEW"
    VALID = "VALID"


class DataValidation(SQLModel, table=True):
    event_key: str = Field(
        foreign_key="frcevent.event_key", 
        primary_key=True, 
        max_length=15
    )
    match_number: int = Field(primary_key=True)
    match_level: str = Field(primary_key=True, max_length=50)
    user_id: UUID = Field(
        primary_key=True,
        default=None,
        foreign_key="users.id"
    )
    team_number: int = Field(foreign_key="teamrecord.team_number")
    organization_id: int = Field(primary_key=True, foreign_key="organization.id")
    timestamp: datetime = Field(default_factory=datetime.now())
    validation_status: ValidationStatus = ValidationStatus.PENDING
    notes: str = Field(max_length=512)