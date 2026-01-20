from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from enum import Enum
from uuid import UUID
from pydantic import ConfigDict

class SuperScoutData(SQLModel):
    """Base fields shared by all superscout data tables."""

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
    match_number: int = Field(primary_key=True)
    match_level: str = Field(primary_key=True, max_length=50)
    user_id: UUID = Field(primary_key=True, foreign_key="users.id")
    organization_id: int = Field(foreign_key="organization.id")
    timestamp: datetime = Field(default_factory=datetime.now)
    notes: Optional[str] = Field(default="")
    stopped_moving: bool = Field(default=False)
    dead_lt_45_seconds: bool = Field(default=False)
    dead_gt_45_seconds: bool = Field(default=False)
    slow_drive: bool = Field(default=False)
    fast_drive: bool = Field(default=False)
    good_driving: bool = Field(default=False)
    bad_driving: bool = Field(default=False)
    drops_game_pieces: bool = Field(default=False)
    lots_of_fouls: bool = Field(default=False)
    tipped: bool = Field(default=False)
    didnt_move: bool = Field(default=False)
    broken: bool = Field(default=False)
    no_show: bool = Field(default=False)
    dnp: bool = Field(default=False)
    played_defense: bool = Field(default=False)
    received_defense: bool = Field(default=False)
    yellow_card: bool = Field(default=False)
    red_card: bool = Field(default=False)
    defense_rating: Optional[int] = Field(default=None, nullable=True, ge=1, le=5)
    driver_rating: Optional[int] = Field(default=None, nullable=True, ge=1, le=5)
    robot_overall: int = Field(ge=1, le=3)