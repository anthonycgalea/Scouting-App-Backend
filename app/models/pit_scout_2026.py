from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from enum import Enum
from uuid import UUID
from .pit_scout import PitScout

class PitEndgame2026(str, Enum):
    NONE = "NONE"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"

class PitScout2026(PitScout, table=True):
    __tablename__ = "pitdata2026"
    hopperCapacity: int = Field(default=0)
    pickupGround: bool = Field(default=False)
    pickupFeeder: bool = Field(default=False)
    trenchBot: bool = Field(default=False)
    bumpBot: bool = Field(default=False)
    startPositionTrenchLeft: bool = Field(default=False)
    startPositionBumpLeft: bool = Field(default=False)
    startPositionCenter: bool = Field(default=False)
    startPositionBumpRight: bool = Field(default=False)
    startPositionTrenchRight: bool = Field(default=False)
    autoPickupCorral: bool = Field(default=False)
    autoPickupDepot: bool = Field(default=False)
    autoFuel: bool = Field(default=False)
    autoFuelCount: int = Field(default=0)
    autoPass: bool = Field(default=False)
    autoPassCount: int = Field(default=0)
    autoClimb: bool = Field(default=False)
    autoNotes: str = Field(default="")
    teleFuel: bool = Field(default=False)
    telePass: bool = Field(default=False)
    teleNotes: str = Field(default="")
    endgame: PitEndgame2026 = Field(default=PitEndgame2026.NONE)
    overallNotes: str = Field(default="")