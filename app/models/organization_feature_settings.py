from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from uuid import UUID, uuid4

class OrganizationFeatureSettings(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id", unique=True)
    
    # Feature toggles
    data_validation: bool = Field(default=False)
    match_video: bool = Field(default=False)
    robot_pictures: bool = Field(default=False)
    scout_schedule: bool = Field(default=False)
    picklist: bool = Field(default=False)

