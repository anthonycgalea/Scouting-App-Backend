from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from uuid import UUID
from .picklist_generator import PickListGenerator

class PickListGenerator2026(PickListGenerator, table=True):
    __tablename__ = "picklistgenerator2026"
    # Autonomous
    autonomous_fuel: float = Field(default=0, ge=0, le=1)
    autonomous_pass: float = Field(default=0, ge=0, le=1)
    autonomous_climb: float = Field(default=0, ge=0, le=1)
    autonomous_points: float = Field(default=0, ge=0, le=1)

    # Teleop Levels
    teleop_fuel: float = Field(default=0, ge=0, le=1)
    teleop_pass: float = Field(default=0, ge=0, le=1)

    # Endgame
    endgame_points: float = Field(default=0, ge=0, le=1)

    # Totals
    total_fuel: float = Field(default=0, ge=0, le=1)
    total_climb: float = Field(default=0, ge=0, le=1)
    total_points: float = Field(default=0, ge=0, le=1)
    
    #TODO: Superscout stuff