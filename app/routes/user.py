from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from auth.dependencies import get_current_user
from db.database import get_session
from models import Organization, UserOrganization
from models.user_organization import UserRole

router = APIRouter()


class OrganizationMembershipResponse(SQLModel):
    id: int
    name: str
    team_number: Optional[int] = None
    role: UserRole
    user_organization_id: int


class OrganizationResponse(SQLModel):
    id: int
    name: str
    team_number: Optional[int] = None


@router.get("/user/info")
async def get_my_profile(user=Depends(get_current_user)):
    return user


@router.get(
    "/user/organizations",
    response_model=List[OrganizationMembershipResponse],
)
async def get_my_organizations(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[OrganizationMembershipResponse]:
    user_id = user.get("id")
    if user_id is None:
        return []

    if isinstance(user_id, str):
        user_id = UUID(user_id)

    statement = (
        select(Organization, UserOrganization)
        .join(UserOrganization, UserOrganization.organization_id == Organization.id)
        .where(UserOrganization.user_id == user_id)
    )
    result = await session.exec(statement)
    memberships = []
    for organization, membership in result.all():
        memberships.append(
            OrganizationMembershipResponse(
                id=organization.id,
                name=organization.name,
                team_number=organization.team_number,
                role=membership.role,
                user_organization_id=membership.id,
            )
        )
    return memberships


@router.get(
    "/organizations",
    response_model=List[OrganizationResponse],
    tags=["Organization"],
)
async def get_all_organizations(
    session: AsyncSession = Depends(get_session),
) -> List[OrganizationResponse]:
    statement = select(Organization)
    result = await session.execute(statement)
    organizations = result.scalars().all()
    if not organizations:
        raise HTTPException(status_code=404, detail="No organizations found for this event")
    return [
        OrganizationResponse(id=o.id, name=o.name, team_number=o.team_number)
        for o in organizations
    ]
