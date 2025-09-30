from sqlmodel import SQLModel, Field

class EventRankings(SQLModel, table=True):
    event_key: str = Field(foreign_key="frcevent.event_key", primary_key=True)
    rank: int = Field(primary_key=True)
    team_number: int = Field(foreign_key="teamrecord.team_number")
    ranking_points: int
    matches_played: int
    ranking_tiebreaker_1: float
    ranking_tiebreaker_2: float

    def get_ranking_score(self) -> float:
        return self.ranking_points/self.matches_played