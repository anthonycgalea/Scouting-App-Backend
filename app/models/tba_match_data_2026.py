from enum import Enum
from typing import Optional

from sqlmodel import Field

from .tba_match_data import Alliance, TBAMatchData


class Endgame2026(str, Enum):
    NONE = "NONE"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class TBAMatchData2026(TBAMatchData, table=True):
    __tablename__ = "tbamatchdata2026"

    # Autonomous
    autoFuel: int = Field(default=0)
    bot1AutoClimb: bool = Field(default=False)
    bot2AutoClimb: bool = Field(default=False)
    bot3AutoClimb: bool = Field(default=False)

    # Teleop
    teleopFuel: int = Field(default=0)

    # Endgame
    bot1endgame: Endgame2026 = Field(default=Endgame2026.NONE)
    bot2endgame: Endgame2026 = Field(default=Endgame2026.NONE)
    bot3endgame: Endgame2026 = Field(default=Endgame2026.NONE)

    wonAuto: bool = Field(default=True)
