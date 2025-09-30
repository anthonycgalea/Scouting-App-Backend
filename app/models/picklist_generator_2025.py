from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from uuid import UUID
from .picklist_generator import PickListGenerator

class PickListGenerator2025(PickListGenerator, table=True):
    __tablename__ = "picklistgenerator2025"
    # Autonomous Levels
    al4c: float = Field(default=0, ge=0, le=1)
    al3c: float = Field(default=0, ge=0, le=1)
    al2c: float = Field(default=0, ge=0, le=1)
    al1c: float = Field(default=0, ge=0, le=1)
    autonomous_coral: float = Field(default=0, ge=0, le=1)
    autonomous_algae: float = Field(default=0, ge=0, le=1)
    autonomous_points: float = Field(default=0, ge=0, le=1)

    # Teleop Levels
    tl4c: float = Field(default=0, ge=0, le=1)
    tl3c: float = Field(default=0, ge=0, le=1)
    tl2c: float = Field(default=0, ge=0, le=1)
    tl1c: float = Field(default=0, ge=0, le=1)
    teleop_coral: float = Field(default=0, ge=0, le=1)
    teleop_algae: float = Field(default=0, ge=0, le=1)
    teleop_points: float = Field(default=0, ge=0, le=1)

    # Net and Processor
    aNet: float = Field(default=0, ge=0, le=1)
    tNet: float = Field(default=0, ge=0, le=1)
    aProcessor: float = Field(default=0, ge=0, le=1)
    tProcessor: float = Field(default=0, ge=0, le=1)

    # Endgame
    endgame_points: float = Field(default=0, ge=0, le=1)

    # Totals
    total_coral: float = Field(default=0, ge=0, le=1)
    total_algae: float = Field(default=0, ge=0, le=1)
    total_game_pieces: float = Field(default=0, ge=0, le=1)
    total_points: float = Field(default=0, ge=0, le=1)
    
    #TODO: Superscout stuff
