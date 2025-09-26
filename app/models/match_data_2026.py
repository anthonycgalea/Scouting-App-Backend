from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from enum import Enum
from uuid import UUID
from .match_data import MatchData, register_match_data_creation_hook

class MatchData2026(MatchData, table=True):
    __tablename__ = "matchdata2026"
    # Autonomous
    # Teleop
    # Endgame


register_match_data_creation_hook(MatchData2026)
    
