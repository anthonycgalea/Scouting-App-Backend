from __future__ import annotations 
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from uuid import UUID
from enum import Enum

class UserRole(str, Enum):
    ADMIN = "ADMIN"
    LEAD = "LEAD"
    MEMBER = "MEMBER"
    GUEST = "GUEST"
    PENDING = "PENDING"

class UserOrganization(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id")
    organization_id: int = Field(foreign_key="organization.id")
    role: UserRole = Field(default=UserRole.MEMBER)
    joined: datetime = Field(default_factory=datetime.now)
    event_key: str = Field(default=None, nullable=True)  # only used for GUEST

# Resolve forward references
UserOrganization.update_forward_refs()
