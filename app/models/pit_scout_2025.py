from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from enum import Enum
from uuid import UUID
from .pit_scout import PitScout

class PitEndgame2025(str, Enum):
    NONE = "NONE"
    PARK = "PARK"
    SHALLOW = "SHALLOW"
    DEEP = "DEEP"

class PitScout2025(PitScout, table=True):
    __tablename__ = "pitdata2025"
    startPositionLeft: bool = Field(default=False)
    startPositionCenter: bool = Field(default=False)
    startPositionRight: bool = Field(default=False)
    pickupGround: bool = Field(default=False)
    pickupFeeder: bool = Field(default=False)
    autoL4Coral: bool = Field(default=False)
    autoL3Coral: bool = Field(default=False)
    autoL2Coral: bool = Field(default=False)
    autoL1Coral: bool = Field(default=False)
    autoCoralCount: int = Field(default=0)
    autoAlgaeNet: int = Field(default=0)
    autoAlgaeProcessor: int = Field(default=0)
    autoNotes: str = Field(default="")
    teleL4Coral: bool = Field(default=False)
    teleL3Coral: bool = Field(default=False)
    teleL2Coral: bool = Field(default=False)
    teleL1Coral: bool = Field(default=False)
    teleAlgaeNet: bool = Field(default=False)
    teleAlgaeProcessor: bool = Field(default=False)
    teleNotes: str = Field(default="")
    endgame: PitEndgame2025 = Field(default=PitEndgame2025.NONE)
    overallNotes: str = Field(default="")