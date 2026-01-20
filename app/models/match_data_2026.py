from sqlmodel import SQLModel, Field, Relationship
from typing import ClassVar, Optional
from datetime import datetime
from enum import Enum
from uuid import UUID
from .match_data import MatchData, register_match_data_creation_hook

class Endgame2026(str, Enum):
    NONE = "NONE"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"

class GameSpecific2026(MatchData):
    __abstract__=True
    AUTO_POINT_WEIGHTS: ClassVar[dict[str, float]] = {
        "autoFuel": 1.0,
        "autoPass": 0.0,
        "autoClimb": 15.0,
    }
    TELEOP_POINT_WEIGHTS: ClassVar[dict[str, float]] = {
        "teleopFuel": 1.0,
        "teleopPass": 0.0,
    }
    ENDGAME_POINT_VALUES: ClassVar[dict[str, float]] = {
        "NONE": 0.0,
        "L1": 10.0,
        "L2": 20.0,
        "L3": 30.0,
    }
    # Autonomous
    autoFuel: int = Field(default=0)
    autoPass: int = Field(default=0)
    autoClimb: int = Field(default=0)
    # Teleop
    teleopFuel: int = Field(default=0)
    teleopPass: int = Field(default=0)
    # Endgame
    endgame: Endgame2026 = Field(default=Endgame2026.NONE)

class MatchData2026(GameSpecific2026, table=True):
    __tablename__ = "matchdata2026"
    

class Prescout2026(GameSpecific2026, table=True):
    """Prescout table that reuses the 2026 scoring schema."""
    __tablename__ = "prescout2026"


register_match_data_creation_hook(MatchData2026)
    
