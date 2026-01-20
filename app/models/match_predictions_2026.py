from .match_predictions import MatchPredictions
from sqlmodel import Field

class MatchPredictions2026(MatchPredictions, table=True):
    __tablename__ = "matchpredictions2026"
    red_energized_rp: float = Field(default=0.0)
    blue_energized_rp: float = Field(default=0.0)
    red_supercharged_rp: float = Field(default=0.0)
    blue_supercharged_rp: float = Field(default=0.0)
    red_traversal_rp: float = Field(default=0.0)
    blue_traversal_rp: float = Field(default=0.0)