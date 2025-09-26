from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, SQLModel
from datetime import datetime
from auth.dependencies import get_current_user
from db.database import get_session
from dotenv import load_dotenv
import os, httpx
import csv
import io
import json
from html import escape
from typing import Dict, Iterable, List, Sequence, Tuple, Union
from uuid import UUID


load_dotenv()

MATCH_SCHEDULE_URL = "https://www.thebluealliance.com/api/v3/event/{event_key}/matches/simple"
TBA_API_KEY = os.getenv("TBA_API_KEY")

MATCH_DATA_2025_COLUMNS = [
    "team_number",
    "event_key",
    "match_number",
    "match_level",
    "notes",
    "al4c",
    "al3c",
    "al2c",
    "al1c",
    "tl4c",
    "tl3c",
    "tl2c",
    "tl1c",
    "aNet",
    "tNet",
    "aProcessor",
    "tProcessor",
    "endgame",
]

MATCH_DATA_2025_OPTIONAL_COLUMNS = {"notes"}

MATCH_DATA_2025_COLUMN_ALIASES = {
    "team_number": ["team_number", "Team #"],
    "event_key": ["event_key", "Event Key"],
    "match_number": ["match_number", "Match #"],
    "match_level": ["match_level", "Match Level"],
    "notes": ["notes", "Notes"],
    "al4c": ["al4c", "Autonomous Level 4 Coral"],
    "al3c": ["al3c", "Autonomous Level 3 Coral"],
    "al2c": ["al2c", "Autonomous Level 2 Coral"],
    "al1c": ["al1c", "Autonomous Level 1 Coral"],
    "tl4c": ["tl4c", "Teleop Level 4 Coral"],
    "tl3c": ["tl3c", "Teleop Level 3 Coral"],
    "tl2c": ["tl2c", "Teleop Level 2 Coral"],
    "tl1c": ["tl1c", "Teleop Level 1 Coral"],
    "aNet": ["aNet", "autoNet"],
    "tNet": ["tNet", "teleopNet"],
    "aProcessor": ["aProcessor", "autoProcessor"],
    "tProcessor": ["tProcessor", "teleopProcessor"],
    "endgame": ["endgame"],
}

LegacyEndgameHeaders = Tuple[str, str]
ResolvedHeader = Union[str, LegacyEndgameHeaders]


def _normalize_header_lookup(fieldnames: Iterable[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    exact_lookup: Dict[str, str] = {}
    lowercase_lookup: Dict[str, str] = {}
    for name in fieldnames:
        exact_lookup[name] = name
        lowercase_lookup[name.lower()] = name
    return exact_lookup, lowercase_lookup


def resolve_match_data_2025_headers(
    fieldnames: Sequence[str],
) -> Tuple[Dict[str, ResolvedHeader], List[str]]:
    """Map expected columns to the actual CSV headers and report missing ones."""

    header_map: Dict[str, ResolvedHeader] = {}
    missing: List[str] = []

    exact_lookup, lowercase_lookup = _normalize_header_lookup(fieldnames)

    for column in MATCH_DATA_2025_COLUMNS:
        aliases = MATCH_DATA_2025_COLUMN_ALIASES.get(column, [column])
        resolved_header: Union[str, None] = None

        for alias in aliases:
            if alias in exact_lookup:
                resolved_header = exact_lookup[alias]
                break
            alias_lower = alias.lower()
            if alias_lower in lowercase_lookup:
                resolved_header = lowercase_lookup[alias_lower]
                break

        if resolved_header is not None:
            header_map[column] = resolved_header
            continue

        if column == "endgame":
            shallow = None
            deep = None
            for alias in ("endgameShallow", "endgame_shallow"):
                if alias in exact_lookup:
                    shallow = exact_lookup[alias]
                    break
                alias_lower = alias.lower()
                if alias_lower in lowercase_lookup:
                    shallow = lowercase_lookup[alias_lower]
                    break
            for alias in ("endgameDeep", "endgame_deep"):
                if alias in exact_lookup:
                    deep = exact_lookup[alias]
                    break
                alias_lower = alias.lower()
                if alias_lower in lowercase_lookup:
                    deep = lowercase_lookup[alias_lower]
                    break

            if shallow and deep:
                header_map[column] = (shallow, deep)
                continue

        if column in MATCH_DATA_2025_OPTIONAL_COLUMNS:
            header_map[column] = ""
        else:
            missing.append(aliases[0])

    return header_map, missing

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
    MatchData2025,
    Endgame2025,
)
from models.user_organization import UserRole
from services.event import (
    MatchExportRequest,
    MatchExportType,
    get_active_event_key_for_user,
    get_match_data_for_event_or_404,
    serialize_match_data_for_export,
)

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


class OrganizationMember(SQLModel):
    userId: UUID
    displayName: str
    email: str
    role: UserRole


class OrganizationMemberChange(SQLModel):
    userId: UUID
    role: UserRole


class OrganizationMemberDeleteRequest(SQLModel):
    userId: UUID


class OrganizationApplicationDeleteRequest(SQLModel):
    userId: UUID


@router.post("/downloadData")
async def download_event_match_data(
    request: MatchExportRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
) -> Response:
    event_code = await get_active_event_key_for_user(session, user)
    match_data = await get_match_data_for_event_or_404(session, event_code)
    match_dicts = serialize_match_data_for_export(match_data)

    if request.file_type == MatchExportType.CSV:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(match_dicts[0].keys()))
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
        headers = list(match_dicts[0].keys())
        header_row = "".join(f"<th>{escape(str(column))}</th>" for column in headers)
        body_rows = "".join(
            "<tr>"
            + "".join(f"<td>{escape(str(row[column]))}</td>" for column in headers)
            + "</tr>"
            for row in match_dicts
        )
        content = (
            "<html><head><meta charset='utf-8'></head><body>"
            f"<table><thead><tr>{header_row}</tr></thead><tbody>{body_rows}</tbody></table>"
            "</body></html>"
        )
        media_type = "application/vnd.ms-excel"
        extension = "xls"
    else:  # pragma: no cover - validation should prevent this
        raise HTTPException(status_code=400, detail="Unsupported file type")

    headers = {
        "Content-Disposition": f'attachment; filename="{event_code}_match_data.{extension}"'
    }

    return Response(content=content, media_type=media_type, headers=headers)


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


@router.get("/members", response_model=List[OrganizationMember])
async def get_organization_members(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[OrganizationMember]:
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
            detail="Only organization admins or leads can access organization members",
        )

    statement = (
        select(UserOrganization, User)
        .join(User, UserOrganization.user_id == User.id)
        .where(UserOrganization.organization_id == membership.organization_id)
        .where(UserOrganization.role != UserRole.PENDING)
    )

    result = await session.exec(statement)
    organization_members = result.all()

    return [
        OrganizationMember(
            userId=user_record.id,
            displayName=user_record.display_name,
            email=user_record.email,
            role=organization_membership.role,
        )
        for organization_membership, user_record in organization_members
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

@router.post("/event/matches/sync")
async def get_match_schedule(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
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
            detail="Only organization admins or leads can sync matches",
        )

    statement = select(OrganizationEvent).where(
        OrganizationEvent.organization_id == membership.organization_id,
        OrganizationEvent.active == True,  # noqa: E712 - SQLAlchemy boolean comparison
    )
    result = await session.execute(statement)
    active_event = result.scalar_one_or_none()

    if active_event is None:
        raise HTTPException(
            status_code=404,
            detail="No active event configured for this organization",
        )

    event_key = active_event.event_key

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
        response = await client.get(
            MATCH_SCHEDULE_URL.format(event_key=event_key), headers=headers
        )
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
            blue3_id=blue3,
        )
        session.add(match_record)

    # 4. Commit all new matches
    await session.commit()
    return {"status": "success", "event": event_key, "matches_inserted": len(match_schedule_json)}


@router.post("/uploadData")
async def upload_match_data(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
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
            detail="Only organization admins or leads can upload match data",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        csv_text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:  # pragma: no cover - defensive programming
        raise HTTPException(status_code=400, detail="Unable to decode CSV file") from exc

    csv_stream = io.StringIO(csv_text)
    reader = csv.DictReader(csv_stream)

    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV file is missing headers")

    header_map, missing_columns = resolve_match_data_2025_headers(reader.fieldnames)
    if missing_columns:
        raise HTTPException(
            status_code=400,
            detail="CSV file is missing required columns: " + ", ".join(missing_columns),
        )

    def parse_int(value: str, default: int = 0) -> int:
        if value is None:
            return default
        value = value.strip()
        if value == "":
            return default
        try:
            return int(float(value))
        except ValueError:
            return default

    processed = 0
    created = 0
    updated = 0

    value_headers: Dict[str, str] = {
        column: header if isinstance(header, str) else ""
        for column, header in header_map.items()
        if column != "endgame"
    }
    endgame_header = header_map.get("endgame")

    for row in reader:
        if not any((value or "").strip() for value in row.values()):
            continue

        def get_row_value(column: str) -> str:
            header = value_headers.get(column, "")
            if not header:
                return ""
            return row.get(header) or ""

        event_key = get_row_value("event_key").strip()
        match_level = get_row_value("match_level").strip()
        match_number_raw = get_row_value("match_number")
        team_number_raw = get_row_value("team_number")

        if not event_key:
            raise HTTPException(status_code=400, detail="Event Key is required for each row")
        if not match_level:
            raise HTTPException(status_code=400, detail="Match Level is required for each row")

        match_number = parse_int(match_number_raw, default=None)
        if match_number is None:
            raise HTTPException(status_code=400, detail="Match # must be an integer")

        team_number = parse_int(team_number_raw, default=None)
        if team_number is None:
            raise HTTPException(status_code=400, detail="Team # must be an integer")

        endgame = Endgame2025.NONE
        if isinstance(endgame_header, tuple):
            shallow_header, deep_header = endgame_header
            if parse_int(row.get(deep_header)) == 1:
                endgame = Endgame2025.DEEP
            elif parse_int(row.get(shallow_header)) == 1:
                endgame = Endgame2025.SHALLOW
        else:
            raw_endgame = (row.get(endgame_header) or "").strip() if endgame_header else ""
            if raw_endgame:
                normalized_endgame = raw_endgame.upper()
                try:
                    endgame = Endgame2025(normalized_endgame)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid endgame value: {raw_endgame}",
                    )

        notes_value = get_row_value("notes").strip()

        data = {
            "season": 1,
            "team_number": team_number,
            "event_key": event_key,
            "match_number": match_number,
            "match_level": match_level,
            "user_id": user_id,
            "organization_id": membership.organization_id,
            "notes": notes_value,
            "timestamp": datetime.now(),
            "al4c": parse_int(get_row_value("al4c")),
            "al3c": parse_int(get_row_value("al3c")),
            "al2c": parse_int(get_row_value("al2c")),
            "al1c": parse_int(get_row_value("al1c")),
            "tl4c": parse_int(get_row_value("tl4c")),
            "tl3c": parse_int(get_row_value("tl3c")),
            "tl2c": parse_int(get_row_value("tl2c")),
            "tl1c": parse_int(get_row_value("tl1c")),
            "aNet": parse_int(get_row_value("aNet")),
            "tNet": parse_int(get_row_value("tNet")),
            "aProcessor": parse_int(get_row_value("aProcessor")),
            "tProcessor": parse_int(get_row_value("tProcessor")),
            "endgame": endgame,
        }

        existing_record = await session.get(
            MatchData2025,
            (
                team_number,
                event_key,
                match_number,
                match_level,
                user_id,
            ),
        )

        if existing_record:
            for field_name, value in data.items():
                setattr(existing_record, field_name, value)
            session.add(existing_record)
            updated += 1
        else:
            match_data = MatchData2025(**data)
            session.add(match_data)
            created += 1

        processed += 1

    await session.commit()

    return {
        "status": "success",
        "processed": processed,
        "created": created,
        "updated": updated,
    }


@router.get("/events", response_model=List[OrganizationEventDetail])
async def get_organization_events(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[OrganizationEventDetail]:
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

    statement = (
        select(OrganizationEvent, FRCEvent)
        .join(FRCEvent, OrganizationEvent.event_key == FRCEvent.event_key)
        .where(OrganizationEvent.organization_id == membership.organization_id)
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


@router.delete("/members", status_code=204)
async def delete_organization_member(
    request: OrganizationMemberDeleteRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
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

    if membership.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only organization admins can remove members")

    target_user_id = request.userId
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

    await session.delete(target_membership)
    await session.commit()

    return Response(status_code=204)
