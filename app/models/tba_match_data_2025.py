from enum import Enum

from sqlmodel import Field

from .tba_match_data import Alliance, TBAMatchData


class Endgame2025(str, Enum):
    NONE = "NONE"
    PARK = "PARK"
    SHALLOW = "SHALLOW"
    DEEP = "DEEP"


class TBAMatchData2025(TBAMatchData, table=True):
    __tablename__ = "tbamatchdata2025"

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
    net: int = Field(default=0)
    processor: int = Field(default=0)

    # Endgame
    endgame: Endgame2025 = Field(default=Endgame2025.NONE)
