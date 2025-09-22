from fastapi import APIRouter, Depends
from auth.dependencies import get_current_user

router = APIRouter()

@router.get("/me")
async def get_my_profile(user=Depends(get_current_user)):
    return user