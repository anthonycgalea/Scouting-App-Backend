from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel


class Alliance(str, Enum):
    RED = "RED"
    BLUE = "BLUE"


class TBAMatchData(SQLModel):
    """Base fields shared by TBA match data tables."""

    event_key: str = Field(
        foreign_key="frcevent.event_key",
        primary_key=True,
        max_length=15,
    )
    match_number: int = Field(primary_key=True)
    match_level: str = Field(primary_key=True, max_length=50)
    alliance: Alliance = Field(primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.now)
