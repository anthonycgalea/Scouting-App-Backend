from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from enum import Enum
from uuid import UUID
from .match_data import MatchData

class Endgame2025(str, Enum):
    NONE = "NONE"
    PARK = "PARK"
    SHALLOW = "SHALLOW"
    DEEP = "DEEP"

class MatchData2025(MatchData, table=True):
    __tablename__ = "matchdata2025"
    # Autonomous Levels
    al4c: int = Field(default=0)
    al3c: int = Field(default=0)
    al2c: int = Field(default=0)
    al1c: int = Field(default=0)

    # Teleop Levels
    tl4c: int = Field(default=0)
    tl3c: int = Field(default=0)
    tl2c: int = Field(default=0)
    tl1c: int = Field(default=0)

    # Net and Processor
    aNet: int = Field(default=0)
    tNet: int = Field(default=0)
    aProcessor: int = Field(default=0)
    tProcessor: int = Field(default=0)

    # Endgame
    endgame: Endgame2025 = Field(default=Endgame2025.NONE)
