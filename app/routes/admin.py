from http.client import HTTPException
from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, delete, SQLModel
from typing import Optional, List, Set
from auth.dependencies import get_current_user
from db.database import get_session
from dotenv import load_dotenv
import requests, os, httpx, asyncio, traceback, aiohttp


router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    #dependencies=[Depends(verify_admin)],
)

from models import (
    Organization,
    OrganizationFeatureSettings,
    TeamRecord,
    FRCEvent,
    TeamEvent
)

load_dotenv()

ALL_TEAMS_URL = "https://www.thebluealliance.com/api/v3/teams/{page_num}/simple"
TBA_API_ENDPOINT = "https://www.thebluealliance.com/api/v3"
TBA_API_KEY = os.getenv("TBA_API_KEY")

semaphore = asyncio.Semaphore(10)

class CreateOrganizationCommand(SQLModel):
    name: str
    team_number: Optional[int]

class OrganizationResponse(SQLModel):
    id: int
    name: str
    team_number: Optional[int]

@router.post("/organizations/create", response_model=OrganizationResponse)
async def create_organization(
    command: CreateOrganizationCommand,
    #user=Depends(get_current_user),
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

@router.post("/teams/update")
async def update_team_list(session: AsyncSession = Depends(get_session)) -> dict:
    pagenum = 0
    teams_to_add = []
    updates = 0

    # 1. Fetch all teams from TBA API
    all_teams = []
    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                url=ALL_TEAMS_URL.format(page_num=str(pagenum)),
                headers={'X-TBA-Auth-Key': TBA_API_KEY, 'accept': 'application/json'}
            )
            team_page = response.json()
            if not team_page:
                break
            all_teams.extend(team_page)
            pagenum += 1

    # 2. Fetch all existing teams from the database in one query
    statement = select(TeamRecord)
    result = await session.exec(statement)
    existing_teams = {team.team_number: team for team in result.all()}

    # 3. Process teams
    for team in all_teams:
        team_number = team["team_number"]
        team_name = team["nickname"]
        location = f"{team['city']}, {team['state_prov']}, {team['country']}"

        if team_number in existing_teams:
            existing_team = existing_teams[team_number]
            if existing_team.team_name != team_name:
                existing_team.team_name = team_name
                updates += 1
        else:
            new_team = TeamRecord(
                team_number,
                team_name
            )
            new_team.location=location
            teams_to_add.append(new_team)

    # 4. Add new teams
    for team in teams_to_add:
        session.add(team)

    # 5. Commit all changes in a single transaction
    await session.commit()

    return {
        "added": len(teams_to_add),
        "updated": updates,
        "total_processed": len(all_teams),
    }   

async def fetch_event_teams(event_key: str, headers: dict):
    async with semaphore:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{TBA_API_ENDPOINT}/event/{event_key}/teams/simple", headers=headers)
            return response.json()

@router.post("/events/registration/{year}")
async def import_event_registration(year: int, session: AsyncSession = Depends(get_session)):
    try:
        # 1. Fetch all events for the year from TBA API
        events_url = f"{TBA_API_ENDPOINT}/events/{year}"
        headers = {"X-TBA-Auth-Key": TBA_API_KEY, "accept": "application/json"}

        async with httpx.AsyncClient() as client:
            response = await client.get(events_url, headers=headers)
            events_data = response.json()

        if not isinstance(events_data, list) or len(events_data) == 0:
            return {"status": "error", "message": f"No events found for year {year} on TBA"}

        # 2. Fetch existing events in DB
        statement = select(FRCEvent)
        result = await session.exec(statement)
        existing_events = {e.event_key: e for e in result.all()}

        # 3. Process each event and prepare async team fetches
        team_fetch_tasks = {}
        for event in events_data:
            if event["event_type"] in [99, 100]:
                continue  # skip off-season events

            event_key = str(event["key"])
            event_name = str(event["name"])
            short_name = str(event["short_name"])
            if year < 2026:
                week = 8 if event["event_type"] in [3, 4] else int(event["week"] + 1)
            else:
                week = 9 if event["event_type"] in [3, 4] else int(event["week"] + 1)
            year_event = int(event_key[:4])

            # Add or update FRCEvent
            if event_key in existing_events:
                db_event = existing_events[event_key]
                if db_event.event_name != event_name or db_event.week != week:
                    db_event.event_name = event_name
                    db_event.short_name = short_name
                    db_event.week = week
                    db_event.year = year_event
            else:
                new_event = FRCEvent(
                    event_key=event_key,
                    event_name=event_name,
                    short_name=short_name,
                    year=year_event,
                    week=week
                )
                session.add(new_event)
                existing_events[event_key] = new_event

            # Schedule async fetch of event teams
            team_fetch_tasks[event_key] = fetch_event_teams(event_key, headers)

        # 4. Fetch all event teams concurrently
        all_team_results = await asyncio.gather(*team_fetch_tasks.values())
        event_keys = list(team_fetch_tasks.keys())

        for idx, event_key in enumerate(event_keys):
            teams_data = all_team_results[idx]

            # Fetch existing team registrations
            statement_teams = select(TeamEvent).where(TeamEvent.event_key == event_key)
            result_teams = await session.exec(statement_teams)
            existing_team_events = {te.team_number: te for te in result_teams.all()}

            current_teams: Set[int] = set()
            for team in teams_data:
                team_number = int(team["team_number"])
                current_teams.add(team_number)
                if team_number not in existing_team_events:
                    new_team_event = TeamEvent(event_key=event_key, team_number=team_number)
                    session.add(new_team_event)

            # Remove registrations for teams no longer present
            for team_number, team_event in existing_team_events.items():
                if team_number not in current_teams:
                    await session.delete(team_event)

        # 5. Commit all changes
        await session.commit()

        return {"status": "success", "year": year, "events_processed": len(events_data)}

    except Exception:
        traceback.print_exc()
        return {"status": "error", "message": f"Error importing events for year {year} from TBA"}