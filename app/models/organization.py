from sqlmodel import SQLModel, Field
from typing import List, Optional

class Organization(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    name: str
    team_number: int = Field(default=None, nullable=True)  # if single team; could also support multiple