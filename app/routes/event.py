import csv
import io
import json
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel.ext.asyncio.session import AsyncSession
from auth.dependencies import get_current_user
from db.database import get_session
from typing import List

from models import Organization, FRCEvent

router = APIRouter(
    prefix="/event",
    tags=["Event"],
)

from services.event import *

@router.get("/match/{matchLevel}/{matchNumber}", tags=["Scout"])
async def get_single_match(
    matchNumber: int,
    matchLevel: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> MatchScheduleResponse:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_match_or_404(session, event_code, matchNumber, matchLevel)


@router.get("/matches")
async def get_match_schedule(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> List[MatchScheduleResponse]:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_match_schedule_or_404(session, event_code)


@router.post("/matches/export")
async def export_match_schedule(
    request: MatchExportRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> Response:
    event_code = await get_active_event_key_for_user(session, user)
    matches = await get_match_schedule_or_404(session, event_code)
    match_dicts = [match.dict() for match in matches]

    if not match_dicts:
        raise HTTPException(status_code=404, detail="No matches available to export")

    if request.file_type == MatchExportType.CSV:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=match_dicts[0].keys())
        writer.writeheader()
        writer.writerows(match_dicts)
        content = buffer.getvalue()
        media_type = "text/csv"
        extension = "csv"
    elif request.file_type == MatchExportType.JSON:
        content = json.dumps(match_dicts, indent=2)
        media_type = "application/json"
        extension = "json"
    elif request.file_type == MatchExportType.XLS:
        headers = match_dicts[0].keys()
        header_row = "".join(f"<th>{escape(str(column))}</th>" for column in headers)
        body_rows = "".join(
            "<tr>" + "".join(
                f"<td>{escape(str(row[column]))}</td>" for column in headers
            ) + "</tr>"
            for row in match_dicts
        )
        content = (
            "<html><head><meta charset='utf-8'></head><body>"
            f"<table><thead><tr>{header_row}</tr></thead><tbody>{body_rows}</tbody></table>"
            "</body></html>"
        )
        media_type = "application/vnd.ms-excel"
        extension = "xls"
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    headers = {
        "Content-Disposition": f'attachment; filename="{event_code}_matches.{extension}"'
    }

    return Response(content=content, media_type=media_type, headers=headers)


@router.get("/organizations")
async def get_event_organizations(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> List[Organization]:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_public_organizations_for_event(session, event_code)


@router.get("/teams")
async def get_team_list(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> List[TeamRecordResponse]:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_team_list_or_404(session, event_code)


@router.get("/info")
async def get_event_info(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> FRCEvent:
    event_code = await get_active_event_key_for_user(session, user)
    return await get_event_or_404(session, event_code)

@router.get("s/{year}")
async def get_event_list(year: int, session: AsyncSession = Depends(get_session)) -> List[EventResponse]:
    return await get_event_list_or_404(session, year)
