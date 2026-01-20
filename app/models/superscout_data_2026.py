from sqlmodel import Field
from enum import Enum

from .superscout_data import SuperScoutData

class StartingPosition2026(str, Enum):
    LEFTTRENCH = "LEFT_TRENCH"
    LEFTBUMP = "LEFT_BUMP"
    HUB = "HUB"
    RIGHTBUMP = "RIGHT_BUMP"
    RIGHTTRENCH = "RIGHT_TRENCH"

class SuperScoutData2026(SuperScoutData, table=True):
    __tablename__ = "superscout_2026"
    startPosition: StartingPosition2026 = Field(nullable=True)
    floor_pickup: bool = Field(default=False)
    auto_corral_pickup: bool = Field(default=False)
    auto_center_pickup: bool = Field(default=False)
    auto_depot_pickup: bool = Field(default=False)
    human_player_feed: bool = Field(default=False)
    passed_fuel: bool = Field(default=False)
    climbs_middle: bool = Field(default=False)
    climbs_end: bool = Field(default=False)