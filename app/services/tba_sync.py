"""Services for synchronising data from The Blue Alliance."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, List, Set

import httpx
from dotenv import load_dotenv
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import FRCEvent, TeamEvent, TeamRecord

load_dotenv()

logger = logging.getLogger(__name__)

ALL_TEAMS_URL = "https://www.thebluealliance.com/api/v3/teams/{page_num}/simple"
TBA_API_ENDPOINT = os.getenv("TBA_API_ENDPOINT", "https://www.thebluealliance.com/api/v3")
TBA_API_KEY = os.getenv("TBA_API_KEY")

# Limit concurrent team fetches to avoid overwhelming the TBA API.
_team_fetch_semaphore = asyncio.Semaphore(10)


class TBASyncError(RuntimeError):
    """Raised when a synchronisation task cannot be completed."""


async def update_team_list(session: AsyncSession) -> Dict[str, int]:
    """Synchronise the list of FRC teams from The Blue Alliance."""

    if not TBA_API_KEY:
        raise TBASyncError("TBA_API_KEY environment variable is not configured.")

    logger.info("Fetching team list from TBA API.")
    page_number = 0
    all_teams: List[dict] = []

    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                url=ALL_TEAMS_URL.format(page_num=str(page_number)),
                headers={"X-TBA-Auth-Key": TBA_API_KEY, "accept": "application/json"},
            )
            response.raise_for_status()

            team_page = response.json()
            if not team_page:
                break

            all_teams.extend(team_page)
            page_number += 1

    logger.info("Fetched %d teams from TBA.", len(all_teams))

    statement = select(TeamRecord)
    result = await session.exec(statement)
    existing_teams = {team.team_number: team for team in result.all()}

    teams_to_add: List[TeamRecord] = []
    updates = 0

    for team in all_teams:
        team_number = int(team["team_number"])
        team_name = team["nickname"]
        location = f"{team['city']}, {team['state_prov']}, {team['country']}"

        if team_number in existing_teams:
            existing_team = existing_teams[team_number]
            if existing_team.team_name != team_name:
                existing_team.team_name = team_name
                updates += 1
            if location and existing_team.location != location:
                existing_team.location = location
        else:
            new_team = TeamRecord(team_number, team_name)
            new_team.location = location
            teams_to_add.append(new_team)

    if teams_to_add:
        logger.info("Adding %d new teams to database.", len(teams_to_add))
        for team in teams_to_add:
            session.add(team)

    await session.commit()

    logger.info(
        "Team sync complete: %d added, %d updated, %d processed.",
        len(teams_to_add),
        updates,
        len(all_teams),
    )

    return {
        "added": len(teams_to_add),
        "updated": updates,
        "total_processed": len(all_teams),
    }


async def _fetch_event_teams(event_key: str, headers: Dict[str, str]) -> List[dict]:
    async with _team_fetch_semaphore:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{TBA_API_ENDPOINT}/event/{event_key}/teams/simple",
                headers=headers,
            )
            response.raise_for_status()
            return response.json()


async def import_event_registration(year: int, session: AsyncSession) -> Dict[str, object]:
    """Synchronise event registrations for the specified ``year``."""

    if not TBA_API_KEY:
        raise TBASyncError("TBA_API_KEY environment variable is not configured.")

    logger.info("Fetching events for %s from TBA API.", year)
    events_url = f"{TBA_API_ENDPOINT}/events/{year}"
    headers = {"X-TBA-Auth-Key": TBA_API_KEY, "accept": "application/json"}

    async with httpx.AsyncClient() as client:
        response = await client.get(events_url, headers=headers)
        response.raise_for_status()
        events_data = response.json()

    if not isinstance(events_data, list) or len(events_data) == 0:
        logger.warning("No events returned for year %s.", year)
        return {"status": "error", "message": f"No events found for year {year} on TBA"}

    statement = select(FRCEvent)
    result = await session.exec(statement)
    existing_events = {event.event_key: event for event in result.all()}

    team_fetch_tasks: Dict[str, asyncio.Task[List[dict]]] = {}

    for event in events_data:
        event_type = event.get("event_type")
        if event_type == 100:
            continue

        event_key = str(event["key"])
        event_name = str(event["name"])
        short_name = str(event["short_name"])

        if event_type == 99:
            week = 99
        elif year < 2026:
            week = 8 if event_type in [3, 4] else int(event["week"] + 1)
        else:
            week = 9 if event_type in [3, 4] else int(event["week"] + 1)

        year_event = int(event_key[:4])

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
                week=week,
            )
            session.add(new_event)
            existing_events[event_key] = new_event

        team_fetch_tasks[event_key] = asyncio.create_task(
            _fetch_event_teams(event_key, headers)
        )

    all_team_results = await asyncio.gather(*team_fetch_tasks.values())
    event_keys = list(team_fetch_tasks.keys())

    for idx, event_key in enumerate(event_keys):
        teams_data = all_team_results[idx]

        statement_teams = select(TeamEvent).where(TeamEvent.event_key == event_key)
        result_teams = await session.exec(statement_teams)
        existing_team_events = {te.team_number: te for te in result_teams.all()}

        current_teams: Set[int] = set()
        for team in teams_data:
            team_number = int(team["team_number"])
            current_teams.add(team_number)
            if team_number not in existing_team_events:
                session.add(TeamEvent(event_key=event_key, team_number=team_number))

        for team_number, team_event in existing_team_events.items():
            if team_number not in current_teams:
                await session.delete(team_event)

    await session.commit()

    logger.info(
        "Imported registrations for %d events in %s.",
        len(events_data),
        year,
    )

    return {"status": "success", "year": year, "events_processed": len(events_data)}
