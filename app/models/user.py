from sqlmodel import SQLModel, Field, Relationship
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional, List

class User(SQLModel, table=True):
    __tablename__ = "users"  # This must match the Supabase table name

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str
    auth_provider: str
    display_name: str
    logged_in_user_org: int = Field(default=None, nullable=True)
    created_at: datetime
    updated_at: datetime = None