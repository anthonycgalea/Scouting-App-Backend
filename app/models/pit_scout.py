from datetime import datetime
from typing import Optional, Type
from uuid import UUID

from sqlalchemy import event, select
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict
from enum import Enum

class DriveTrain(str, Enum):
    SWERVE = "SWERVE"
    TANK = "TANK"
    MECANUM = "MECANUM"
    HDRIVE = "H-DRIVE"
    OTHER = "OTHER"

class PitScout(SQLModel):
    model_config = ConfigDict(extra="allow")

    season: int = Field(foreign_key="season.id")
    team_number: int = Field(
        foreign_key="teamrecord.team_number",
        primary_key=True
    )
    event_key: str = Field(
        foreign_key="frcevent.event_key",
        primary_key=True,
        max_length=15,
    )
    user_id: UUID = Field(primary_key=True, foreign_key="users.id")
    organization_id: int = Field(foreign_key="organization.id")
    timestamp: datetime = Field(default_factory=datetime.now)
    notes: Optional[str] = Field(default="")
    robot_weight: Optional[int] = Field(default=0)
    drivetrain: DriveTrain = Field(default=DriveTrain.TANK)
    driveteam: Optional[str] = Field(default="")
