from fastapi import HTTPException
from sqlmodel import select, delete, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from uuid import UUID
from typing import List

from models import (
    MatchData,
    MatchData2025,
    MatchData2026,
    UserOrganization,
    User, 
    Organization
)

async def get_already_scouted_matches(session: AsyncSession, eventCode: str, user):
    #check if user is part of an organization that has the orgEvent

    #if user is guest, verify event code

    #if valid, return logged in organization's scouted matches
    pass

async def get_already_scouted_match(session: AsyncSession, eventCode: str, matchLevel: str, matchNumber: int, user):
    #check if user is part of an organization that has the orgEvent

    #if user is guest, verify event code

    #if valid, return logged in organization's scouted match
    pass

async def get_already_scouted_team_match(session: AsyncSession, eventCode: str, matchLevel: str, matchNumber: int, teamNumber: int, user):
    #check if user is part of an organization that has the orgEvent

    #if user is guest, verify event code

    #if valid, return logged in organization's scouted match
    pass

async def batch_submit_match(session: AsyncSession, matches: List[MatchData], user: User):
    for match in matches:
        submit_scouted_match(session, match, user)

async def batch_update_match(session: AsyncSession, matches: List[MatchData], user: User):
    for match in matches:
        update_scouted_match(session, match, user)

async def update_scouted_match(session: AsyncSession, match: MatchData, user: User):
    #check if user is part of organization specified in match.organization_id

    #if user is guest, verify event code

    #if valid, go to switch for match submission
    if (match.season == 1): #2025 REEFSCAPE
        await update_2025_match(session, MatchData2025(match), user)
    elif (match.season == 2): #2026 REBUILT
        await update_2026_match(session, MatchData2026(match), user)


async def submit_scouted_match(session: AsyncSession, match: MatchData, user: User):
    #check if user is part of organization specified in match.organization_id

    #if user is guest, verify event code

    #if valid, go to switch for match submission
    if (match.season == 1): #2025 REEFSCAPE
        await submit_2025_match(session, MatchData2025(match), user)
    elif (match.season == 2): #2026 REBUILT
        await submit_2026_match(session, MatchData2026(match), user)


async def submit_2025_match(session: AsyncSession, match: MatchData2025, user: User) -> None:
    pass

async def update_2025_match(session: AsyncSession, match: MatchData2025, user: User) -> None:
    pass

async def submit_2026_match(session: AsyncSession, match: MatchData2026, user: User) -> None:
    pass

async def update_2026_match(session: AsyncSession, match: MatchData2026, user: User) -> None:
    pass