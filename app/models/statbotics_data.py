from sqlmodel import SQLModel, Field

class StatboticsData(SQLModel, table=True):
    __tablename__ = "statbotics_data"
    event_key: str = Field(foreign_key="frcevent.event_key", primary_key=True)
    team_number: int = Field(foreign_key="teamrecord.team_number", primary_key=True)
    total_points: float
    auto_points: float
    teleop_points: float
    endgame_points: float