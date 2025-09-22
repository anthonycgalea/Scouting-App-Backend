from sqlmodel import SQLModel, Field, Relationship

class TeamEvent(SQLModel, table=True):
    __tablename__ = "teamevent"

    event_key: str = Field(foreign_key="frcevent.event_key", primary_key=True)
    team_number: int = Field(foreign_key="teamrecord.team_number", primary_key=True)

    def __init__(self, event_key, team_number):
        self.event_key = event_key
        self.team_number = team_number