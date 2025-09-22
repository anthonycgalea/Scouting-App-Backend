from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from enum import Enum
from uuid import UUID
from .match_data import MatchData

class MatchData2026(MatchData, table=True):
    __tablename__ = "matchdata2026"
    # Autonomous 
    # Teleop
    # Endgame
    