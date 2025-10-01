from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel


class PickListRank(SQLModel, table=True):
    __tablename__ = "picklist_rank"

    picklist_id: UUID = Field(foreign_key="picklist.id", primary_key=True)
    rank: int = Field(primary_key=True)
    team_number: int = Field(foreign_key="teamrecord.team_number")
    notes: Optional[str] = Field(default="")
    dnp: bool = Field(default=False)
