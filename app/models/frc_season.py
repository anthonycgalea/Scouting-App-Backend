from sqlmodel import SQLModel, Field

class Season(SQLModel, table=True):
    id: int = Field(primary_key=True)
    year: int
    name: str