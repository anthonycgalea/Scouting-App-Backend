from enum import Enum
from uuid import UUID

from sqlmodel import Field, SQLModel


class OrgEventAllianceInviteStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"


class OrganizationEventAlliance(SQLModel, table=True):
    __tablename__ = "organization_event_alliance"

    orgevent_Uid: UUID = Field(
        foreign_key="organizationevent.id", primary_key=True
    )
    other_organization_id: int = Field(
        foreign_key="organization.id", primary_key=True
    )
    org_invite_status: OrgEventAllianceInviteStatus = Field(
        default=OrgEventAllianceInviteStatus.PENDING
    )
