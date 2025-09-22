from http.client import HTTPException
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, delete, SQLModel
from auth.dependencies import get_current_user
from db.database import get_session
from dotenv import load_dotenv
import os, httpx


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
    MatchSchedule
)

class CreateOrgEventCommand(SQLModel):
    OrganizationId: int
    EventKey: str

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