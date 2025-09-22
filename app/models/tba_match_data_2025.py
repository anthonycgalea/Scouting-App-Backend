from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from enum import Enum

class Endgame2025(str, Enum):
    NONE = "NONE"
    PARK = "PARK"
    SHALLOW = "SHALLOW"
    DEEP = "DEEP"

class Alliance(str, Enum):
    RED="RED"
    BLUE="BLUE"

class TBAMatchData2025(SQLModel, table=True):
    team_number: int = Field(
        foreign_key="teamrecord.team_number", 
        primary_key=True
    )
    event_key: str = Field(
        foreign_key="frcevent.event_key", 
        primary_key=True, 
        max_length=15
    )
    match_number: int = Field(primary_key=True)
    match_level: str = Field(primary_key=True, max_length=50)
    alliance: Alliance = Field(default=Alliance.RED)
    timestamp: datetime = Field(default_factory=datetime.now())


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
    