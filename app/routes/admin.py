from uuid import UUID
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.dependencies import require_site_admin
from app.db.database import get_session


router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_site_admin)],
)

from app.models import (
    Organization,
    OrganizationFeatureSettings,
    User,
    UserOrganization,
    UserRole,
)

class CreateOrganizationCommand(SQLModel):
    name: str
    team_number: Optional[int]

class OrganizationResponse(SQLModel):
    id: int
    name: str
    team_number: Optional[int]


class ManageOrganizationMemberRequest(SQLModel):
    user_id: UUID
    organization_id: int


class ManageOrganizationMemberResponse(SQLModel):
    user_organization_id: int
    role: UserRole


class AdminUserResponse(SQLModel):
    id: UUID
    email: str
    auth_provider: str
    display_name: str
    logged_in_user_org: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


@router.get("/users", response_model=List[AdminUserResponse])
async def get_all_users(
    session: AsyncSession = Depends(get_session),
) -> List[AdminUserResponse]:
    statement = select(User)
    result = await session.exec(statement)
    users = result.all()

    return [
        AdminUserResponse(
            id=user.id,
            email=user.email,
            auth_provider=user.auth_provider,
            display_name=user.display_name,
            logged_in_user_org=user.logged_in_user_org,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
        for user in users
    ]


@router.post("/organizations/create", response_model=OrganizationResponse)
async def create_organization(
    command: CreateOrganizationCommand,
    session: AsyncSession = Depends(get_session)
) -> OrganizationResponse:
    #TODO: validate website administrator
    newOrg: Organization = Organization(
        name=command.name,
        team_number=command.team_number
    )
    session.add(newOrg)
    await session.flush()
    await session.refresh(newOrg)

    session.add(OrganizationFeatureSettings(
        organization_id=newOrg.id
    ))

    await session.commit()
    return OrganizationResponse(
        id=newOrg.id,
        name=newOrg.name,
        team_number=newOrg.team_number
    )

@router.post(
    "/organizations/members",
    response_model=ManageOrganizationMemberResponse,
)
async def add_or_promote_organization_member(
    request: ManageOrganizationMemberRequest,
    session: AsyncSession = Depends(get_session),
) -> ManageOrganizationMemberResponse:
    statement = select(UserOrganization).where(
        UserOrganization.user_id == request.user_id,
        UserOrganization.organization_id == request.organization_id,
    )
    result = await session.exec(statement)
    membership = result.first()

    if membership is None:
        membership = UserOrganization(
            user_id=request.user_id,
            organization_id=request.organization_id,
            role=UserRole.ADMIN,
        )
        session.add(membership)
        await session.commit()
        await session.refresh(membership)
    else:
        if membership.role != UserRole.ADMIN:
            membership.role = UserRole.ADMIN
            session.add(membership)
            await session.commit()
        await session.refresh(membership)

    return ManageOrganizationMemberResponse(
        user_organization_id=membership.id,
        role=membership.role,
    )
