from sqlmodel import SQLModel, Field
from typing import Optional

class TeamRecord(SQLModel, table=True):
    __tablename__ = "teamrecord"

    team_number: int = Field(primary_key = True)
    team_name: str
    location: Optional[str] = None
    rookieYear: Optional[str] = None


    def __init__(self, teamNumber, teamName):
        self.team_number = teamNumber
        self.team_name = teamName
    
    