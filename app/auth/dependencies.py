import os
from jose import jwt, JWTError
from fastapi import Header, HTTPException, Depends
from dotenv import load_dotenv
from sqlmodel.ext.asyncio.session import AsyncSession
from datetime import datetime

from db.database import get_session
from models import User

# Load .env file
load_dotenv()

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

if not SUPABASE_JWT_SECRET:
    raise RuntimeError("SUPABASE_JWT_SECRET is not set in environment variables")

async def get_current_user(
    authorization: str = Header(...),
    session: AsyncSession = Depends(get_session)
):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = authorization.split(" ")[1]

    try:
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

        db_user = await session.get(User, user_id)
        if not db_user:
            db_user = User(
                id=user_id,
                email=email,
                auth_provider="discord",
                display_name=display_name,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            session.add(db_user)
            await session.commit()
            await session.refresh(db_user)

        return {
            "id": str(db_user.id),
            "displayName": display_name,
            "email": email,
        }

    except JWTError as e:
        print("❌ JWT decode error:", str(e))
        raise HTTPException(status_code=401, detail="Invalid token")