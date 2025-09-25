from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, SQLModel
from datetime import datetime
from auth.dependencies import get_current_user
from db.database import get_session
from dotenv import load_dotenv
import os, httpx
from typing import List
from uuid import UUID


load_dotenv()

MATCH_SCHEDULE_URL = "https://www.thebluealliance.com/api/v3/event/{event_key}/matches/simple"
TBA_API_KEY = os.getenv("TBA_API_KEY")

router = APIRouter(
    prefix="/organization",
    tags=["Organization"]    
)

from models import (
    Organization,
    OrganizationEvent,
    FRCEvent,
    MatchSchedule,
    User,
    UserOrganization,
)
from models.user_organization import UserRole

class CreateOrgEventCommand(SQLModel):
    OrganizationId: int
    EventKey: str


class OrganizationEventDetail(SQLModel):
    eventKey: str
    shortName: str
    eventName: str
    week: int
    isPublic: bool
    isActive: bool


class UpdateOrganizationEventRequest(SQLModel):
    eventKey: str
    isPublic: bool
    isActive: bool


class OrganizationApplication(SQLModel):
    userId: UUID
    displayName: str
    email: str
    role: UserRole
    joined: datetime


class OrganizationMemberChange(SQLModel):
    userId: UUID
    role: UserRole


class OrganizationApplicationDeleteRequest(SQLModel):
    userId: UUID


@router.get("/applications", response_model=List[OrganizationApplication])
async def get_pending_applications(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[OrganizationApplication]:
    user_id = user.get("id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    membership_id = user.get("user_org")
    if membership_id is None:
        raise HTTPException(
            status_code=404, detail="User is not logged into an organization"
        )

    if isinstance(user_id, str):
        try:
            user_id = UUID(user_id)
        except ValueError as exc:  # pragma: no cover - defensive programming
            raise HTTPException(status_code=400, detail="Invalid user identifier") from exc

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    if membership.user_id != user_id:
        raise HTTPException(status_code=403, detail="User does not belong to this organization")

    if membership.role not in {UserRole.ADMIN, UserRole.LEAD}:
        raise HTTPException(
            status_code=403,
            detail="Only organization admins or leads can access organization applications",
        )

    statement = (
        select(UserOrganization, User)
        .join(User, UserOrganization.user_id == User.id)
        .where(UserOrganization.organization_id == membership.organization_id)
        .where(UserOrganization.role == UserRole.PENDING)
    )

    result = await session.exec(statement)
    pending_members = result.all()

    return [
        OrganizationApplication(
            userId=user_record.id,
            displayName=user_record.display_name,
            email=user_record.email,
            role=organization_membership.role,
            joined=organization_membership.joined,
        )
        for organization_membership, user_record in pending_members
    ]


@router.delete("/applications", status_code=204)
async def delete_pending_application(
    request: OrganizationApplicationDeleteRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    user_id = user.get("id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    membership_id = user.get("user_org")
    if membership_id is None:
        raise HTTPException(
            status_code=404, detail="User is not logged into an organization"
        )

    if isinstance(user_id, str):
        try:
            user_id = UUID(user_id)
        except ValueError as exc:  # pragma: no cover - defensive programming
            raise HTTPException(status_code=400, detail="Invalid user identifier") from exc

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    if membership.user_id != user_id:
        raise HTTPException(status_code=403, detail="User does not belong to this organization")

    if membership.role not in {UserRole.ADMIN, UserRole.LEAD}:
        raise HTTPException(
            status_code=403,
            detail="Only organization admins or leads can manage organization applications",
        )

    statement = (
        select(UserOrganization)
        .where(UserOrganization.organization_id == membership.organization_id)
        .where(UserOrganization.user_id == request.userId)
    )

    result = await session.exec(statement)
    pending_membership = result.first()

    if pending_membership is None:
        raise HTTPException(status_code=404, detail="Requested user is not part of this organization")

    if pending_membership.role != UserRole.PENDING:
        raise HTTPException(status_code=400, detail="Only pending applications can be removed")

    await session.delete(pending_membership)
    await session.commit()

    return Response(status_code=204)

@router.post("/createEvent", response_model=OrganizationEvent)
async def createOrganizationEvent(
    command: CreateOrgEventCommand,
    #user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
) -> OrganizationEvent:
    # TODO: validate organization administrator

    # Check if the event exists
    statement = select(FRCEvent).where(FRCEvent.event_key == command.EventKey)
    result = await session.exec(statement)
    event = result.first()
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {command.EventKey} not found")

    newOrgEvent = OrganizationEvent(
        organization_id=command.OrganizationId,
        event_key=command.EventKey
    )
    session.add(newOrgEvent)
    await session.commit()
    await session.refresh(newOrgEvent)

    return newOrgEvent

@router.post("/event/{event_key}/matches/sync")
async def get_match_schedule(event_key: str, session: AsyncSession = Depends(get_session)):

    # 1. Delete existing matches for the event
    statement = select(MatchSchedule).where(MatchSchedule.event_key == event_key)
    result = await session.exec(statement)
    existing_matches = result.all()
    for match in existing_matches:
        await session.delete(match)
    await session.commit()

    # 2. Fetch match schedule from TBA
    headers = {"X-TBA-Auth-Key": TBA_API_KEY, "accept": "application/json"}
    async with httpx.AsyncClient() as client:
        response = await client.get(MATCH_SCHEDULE_URL.format(event_key=event_key), headers=headers)
        match_schedule_json = response.json()

    # 3. Insert matches into DB
    for match in match_schedule_json:
        alliances = match["alliances"]
        if match["comp_level"] == "sf":
            match_number = match["set_number"]
        else:
            match_number = match["match_number"]

        redteams = alliances["red"]["team_keys"]
        blueteams = alliances["blue"]["team_keys"]

        red1 = int(redteams[0][3:])
        red2 = int(redteams[1][3:])
        red3 = int(redteams[2][3:])
        blue1 = int(blueteams[0][3:])
        blue2 = int(blueteams[1][3:])
        blue3 = int(blueteams[2][3:])

        match_record = MatchSchedule(
            event_key=event_key,
            match_number=match_number,
            match_level=match["comp_level"],
            red1_id=red1,
            red2_id=red2,
            red3_id=red3,
            blue1_id=blue1,
            blue2_id=blue2,
            blue3_id=blue3
        )
        session.add(match_record)

    # 4. Commit all new matches
    await session.commit()
    return {"status": "success", "event": event_key, "matches_inserted": len(match_schedule_json)}


@router.get("/{organization_id}/events", response_model=List[OrganizationEventDetail])
async def get_organization_events(
    organization_id: int,
    session: AsyncSession = Depends(get_session),
) -> List[OrganizationEventDetail]:
    statement = (
        select(OrganizationEvent, FRCEvent)
        .join(FRCEvent, OrganizationEvent.event_key == FRCEvent.event_key)
        .where(OrganizationEvent.organization_id == organization_id)
    )
    result = await session.exec(statement)
    events = result.all()
    if not events:
        raise HTTPException(status_code=404, detail="No events found for this organization")
    return [
        OrganizationEventDetail(
            isPublic=organization_event.public_data,
            isActive=organization_event.active,
            eventName=frc_event.event_name,
            shortName=frc_event.short_name,
            eventKey=frc_event.event_key,
            week=frc_event.week
        )
        for organization_event, frc_event in events
    ]


@router.patch("/events")
async def update_organization_events(
    updates: List[UpdateOrganizationEventRequest],
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not updates:
        raise HTTPException(status_code=400, detail="No event updates provided")

    active_updates = sum(1 for update in updates if update.isActive)
    if active_updates != 1:
        raise HTTPException(status_code=400, detail="Exactly one event must be active")

    user_id = user.get("id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    if isinstance(user_id, str):
        try:
            user_id = UUID(user_id)
        except ValueError as exc:  # pragma: no cover - defensive programming
            raise HTTPException(status_code=400, detail="Invalid user identifier") from exc

    membership_id = user.get("user_org")
    if membership_id is None:
        raise HTTPException(status_code=404, detail="User is not logged into an organization")

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    if membership.user_id != user_id:
        raise HTTPException(status_code=403, detail="User does not belong to this organization")

    statement = select(OrganizationEvent).where(
        OrganizationEvent.organization_id == membership.organization_id
    )
    result = await session.exec(statement)
    organization_events = result.all()

    if not organization_events:
        raise HTTPException(status_code=404, detail="No events found for this organization")

    update_map = {}
    for update in updates:
        if update.eventKey in update_map:
            raise HTTPException(status_code=400, detail="Duplicate event keys provided")
        update_map[update.eventKey] = update

    if len(update_map) != len(organization_events):
        raise HTTPException(
            status_code=400,
            detail="Updates must be provided for every organization event",
        )

    for organization_event in organization_events:
        event_update = update_map.get(organization_event.event_key)
        if event_update is None:
            raise HTTPException(status_code=400, detail="Unknown event key provided")

        organization_event.public_data = event_update.isPublic
        organization_event.active = event_update.isActive
        session.add(organization_event)

    await session.commit()

    return {"status": "success"}


@router.patch("/members")
async def update_organization_member(
    change: OrganizationMemberChange,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    user_id = user.get("id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    if isinstance(user_id, str):
        try:
            user_id = UUID(user_id)
        except ValueError as exc:  # pragma: no cover - defensive programming
            raise HTTPException(status_code=400, detail="Invalid user identifier") from exc

    membership_id = user.get("user_org")
    if membership_id is None:
        raise HTTPException(status_code=404, detail="User is not logged into an organization")

    membership = await session.get(UserOrganization, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found")

    if membership.user_id != user_id:
        raise HTTPException(status_code=403, detail="User does not belong to this organization")

    if membership.role not in {UserRole.ADMIN, UserRole.LEAD}:
        raise HTTPException(
            status_code=403,
            detail="Only organization admins or leads can manage members",
        )

    if change.role in {UserRole.ADMIN, UserRole.LEAD} and membership.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Only organization admins can assign admin or lead roles",
        )

    target_user_id = change.userId
    if isinstance(target_user_id, str):
        try:
            target_user_id = UUID(target_user_id)
        except ValueError as exc:  # pragma: no cover - defensive programming
            raise HTTPException(status_code=400, detail="Invalid member identifier") from exc

    statement = select(UserOrganization).where(
        UserOrganization.user_id == target_user_id,
        UserOrganization.organization_id == membership.organization_id,
    )
    result = await session.exec(statement)
    target_membership = result.first()

    if target_membership is None:
        raise HTTPException(status_code=404, detail="Organization membership not found for user")

    target_membership.role = change.role
    session.add(target_membership)
    await session.commit()
    await session.refresh(target_membership)

    return {"status": "success", "userId": str(target_membership.user_id), "role": target_membership.role}
