from sqlmodel import SQLModel, Field
from typing import Optional

class Season(SQLModel, table=True):
    id: int = Field(primary_key=True)
    year: int
    name: str
    active: Optional[bool]