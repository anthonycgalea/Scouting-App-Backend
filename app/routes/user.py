from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from auth.dependencies import get_current_user
from db.database import get_session
from models import Organization, UserOrganization, User
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


class OrganizationApplicationRequest(SQLModel):
    organization_id: int


class UpdateUserOrganizationRequest(SQLModel):
    user_organization_id: int


class UpdateUserOrganizationResponse(SQLModel):
    user_organization_id: int


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
        .where(UserOrganization.role != "PENDING")
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

@router.get("/user/role")
async def get_my_role(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    user_id = user.get("id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    organization_id = user.get("user_org")
    if organization_id is None:
        raise HTTPException(
            status_code=404, detail="User is not logged into an organization"
        )

    if isinstance(user_id, str):
        user_id = UUID(user_id)

    membership_statement = select(UserOrganization).where(
        UserOrganization.user_id == user_id,
        UserOrganization.id == organization_id,
    )
    membership_result = await session.exec(membership_statement)
    membership = membership_result.first()

    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    return {
        "role": membership.role.value
    }





@router.post(
    "/user/organization/apply",
    response_model=OrganizationMembershipResponse,
    status_code=status.HTTP_201_CREATED,
)
async def apply_to_organization(
    application: OrganizationApplicationRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> OrganizationMembershipResponse:
    user_id = user.get("id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    if isinstance(user_id, str):
        user_id = UUID(user_id)

    organization = await session.get(Organization, application.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    existing_statement = select(UserOrganization).where(
        UserOrganization.user_id == user_id,
        UserOrganization.organization_id == application.organization_id,
    )
    existing_membership = await session.exec(existing_statement)
    if existing_membership.first() is not None:
        raise HTTPException(
            status_code=400,
            detail="User has already applied or is a member of this organization",
        )

    membership = UserOrganization(
        user_id=user_id,
        organization_id=application.organization_id,
        role=UserRole.PENDING,
    )
    session.add(membership)
    await session.commit()
    await session.refresh(membership)

    return OrganizationMembershipResponse(
        id=organization.id,
        name=organization.name,
        team_number=organization.team_number,
        role=membership.role,
        user_organization_id=membership.id,
    )


@router.patch(
    "/user/organization",
    response_model=UpdateUserOrganizationResponse,
)
async def update_user_logged_in_organization(
    update: UpdateUserOrganizationRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UpdateUserOrganizationResponse:
    user_id = user.get("id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    if isinstance(user_id, str):
        try:
            user_id = UUID(user_id)
        except ValueError as exc:  # pragma: no cover - defensive programming
            raise HTTPException(status_code=400, detail="Invalid user identifier") from exc

    membership = await session.get(UserOrganization, update.user_organization_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="User organization membership not found")

    if membership.user_id != user_id:
        raise HTTPException(status_code=403, detail="User does not belong to this organization")

    db_user = await session.get(User, user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    db_user.logged_in_user_org = update.user_organization_id
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)

    return UpdateUserOrganizationResponse(user_organization_id=db_user.logged_in_user_org)
