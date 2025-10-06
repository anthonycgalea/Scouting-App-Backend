from sqlmodel import Field
from enum import Enum

from .superscout_data import SuperScoutData

class StartingPosition(str, Enum):
    LEFT = "LEFT"
    CENTER = "CENTER"
    RIGHT = "RIGHT"

class SuperScoutData2025(SuperScoutData, table=True):
    __tablename__ = "superscout_2025"
    startPosition: StartingPosition = Field(nullable=True)
    floor_algae: bool = Field(default=False)
    floor_coral: bool = Field(default=False)
    holds_both_pieces: bool = Field(default=False)

