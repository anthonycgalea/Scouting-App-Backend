from __future__ import annotations 
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum

class AutoAssignUserOrg(SQLModel, table=True):
    __tablename__ = "auto_assign_user_org"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id")
    domain: Optional[str] = Field(default="")