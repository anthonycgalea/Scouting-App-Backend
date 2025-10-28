from sqlmodel import SQLModel, Field
from datetime import datetime

class RankingPredictions(SQLModel, table=True):
    __tablename__ = "ranking_predictions"
    event_key: str = Field(foreign_key="frcevent.event_key", primary_key=True)
    organization_id: int = Field(primary_key=True, foreign_key="organization.id")
    timestamp: datetime = Field(default_factory=datetime.now)
    team_number: int = Field(primary_key=True, foreign_key="teamrecord.team_number")
    rank_5: int
    rank_95: int
    median_rank: int
    mean_rank: float
    mean_rp: float