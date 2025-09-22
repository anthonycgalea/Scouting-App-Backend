from sqlmodel import SQLModel, Field
from typing import Optional

class FRCEvent(SQLModel, table=True):
    __tablename__ = "frcevent"

    event_key: str = Field(primary_key=True)
    event_name: str
    short_name: Optional[str]
    year: int
    week: int

    def __init__(self, event_key, event_name, year, week, short_name=None):
        self.event_key = event_key
        self.event_name = event_name
        self.year=year
        self.week=week
        if (short_name):
            self.short_name=short_name