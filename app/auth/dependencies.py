import logging
import os
from datetime import datetime

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt
from dotenv import load_dotenv
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from uuid import UUID

from app.db.database import get_session
from app.models import AutoAssignUserOrg, SiteAdmins, User, UserOrganization, UserRole

# Load .env file
load_dotenv()

logger = logging.getLogger(__name__)

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

if not SUPABASE_JWT_SECRET:
    raise RuntimeError("SUPABASE_JWT_SECRET is not set in environment variables")


async def get_current_user(
    authorization: str = Header(...),
    session: AsyncSession = Depends(get_session)
):
    if not authorization.startswith("Bearer "):
        logger.warning("Authorization header missing Bearer token prefix")
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = authorization.split(" ")[1]

    try:
        logger.debug("Decoding JWT token for authorization")
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False}
        )

        user_id = payload.get("sub")
        email = payload.get("email")
        display_name = (
            payload.get("user_metadata", {}).get("full_name")
            or payload.get("user_metadata", {}).get("display_name")
            or email
        )

        logger.debug("Looking up user %s in database", user_id)
        db_user = await session.get(User, user_id)
        if not db_user:
            logger.info("User %s not found in database. Creating new record.", user_id)
            now = datetime.now()
            db_user = User(
                id=user_id,
                email=email,
                auth_provider="discord",
                display_name=display_name,
                created_at=now,
                updated_at=now,
            )
            session.add(db_user)
            await session.flush()

            domain = None
            if email and "@" in email:
                domain = email.split("@", 1)[1].lower()

            if domain:
                auto_assign_result = await session.exec(
                    select(AutoAssignUserOrg).where(AutoAssignUserOrg.domain == domain)
                )
                auto_assign_entry = auto_assign_result.first()

                if auto_assign_entry:
                    membership = UserOrganization(
                        user_id=db_user.id,
                        organization_id=auto_assign_entry.organization_id,
                        role=UserRole.MEMBER,
                    )
                    session.add(membership)
                    await session.flush()
                    db_user.logged_in_user_org = membership.id

            await session.commit()
            await session.refresh(db_user)

        logger.debug(
            "Authenticated request for user %s (%s) with organization %s",
            user_id,
            email,
            db_user.logged_in_user_org,
        )

        return {
            "id": str(db_user.id),
            "displayName": db_user.display_name,
            "email": db_user.email,
            "user_org": db_user.logged_in_user_org
        }

    except JWTError as exc:
        logger.exception("JWT decode error while processing authorization header")
        raise HTTPException(status_code=401, detail="Invalid token") from exc


async def require_site_admin(
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        user_id = UUID(current_user["id"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Site admin access required") from exc

    site_admin = await session.get(SiteAdmins, user_id)
    if not site_admin:
        raise HTTPException(status_code=403, detail="Site admin access required")

    return current_user
