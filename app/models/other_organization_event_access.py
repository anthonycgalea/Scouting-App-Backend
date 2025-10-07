from sqlmodel import SQLModel, Field
from uuid import UUID, uuid4
from enum import Enum

class OrgEventInviteStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"

class OrganizationEventCollaboration(SQLModel, table=True):
    __tablename__ = "organization_event_collaboration"
    orgevent_Uid: UUID = Field(default_factory=uuid4, primary_key=True)
    other_organization_id: int = Field(foreign_key="organization.id", primary_key=True)
    org_invite_status: OrgEventInviteStatus = Field(default=OrgEventInviteStatus.PENDING)