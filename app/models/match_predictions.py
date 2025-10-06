from datetime import datetime
from typing import Optional, Type
from uuid import UUID

from sqlalchemy import event, select
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict


class MatchPredictions(SQLModel):
    """Base fields shared by all match prediction tables."""

    model_config = ConfigDict(extra="allow")

    season: int = Field(foreign_key="season.id")
    event_key: str = Field(
        foreign_key="frcevent.event_key",
        primary_key=True,
        max_length=15,
    )
    match_number: int = Field(primary_key=True)
    match_level: str = Field(primary_key=True, max_length=50)
    organization_id: int = Field(primary_key=True, foreign_key="organization.id")
    timestamp: datetime = Field(default_factory=datetime.now)
    red_alliance_win_pct: float = Field(default=0.0)
    blue_alliance_win_pct: float = Field(default=0.0)
    n_samples: int = Field(default=10000)