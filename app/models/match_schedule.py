from sqlmodel import SQLModel, Field, Relationship


class MatchSchedule(SQLModel, table=True):
    event_key: str = Field(foreign_key="frcevent.event_key", primary_key=True)
    match_number: int = Field(primary_key=True)
    match_level: str = Field(primary_key=True)

    # Foreign keys to TeamRecord — required
    red1_id: int = Field(foreign_key="teamrecord.team_number")
    red2_id: int = Field(foreign_key="teamrecord.team_number")
    red3_id: int = Field(foreign_key="teamrecord.team_number")
    blue1_id: int = Field(foreign_key="teamrecord.team_number")
    blue2_id: int = Field(foreign_key="teamrecord.team_number")
    blue3_id: int = Field(foreign_key="teamrecord.team_number")
