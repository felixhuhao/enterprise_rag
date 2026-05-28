"""Current user info — GET /api/me."""

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser
from app.deps import verify_token

router = APIRouter()


@router.get("/me")
async def get_me(current_user: CurrentUser = Depends(verify_token)):
    return {
        "user_id": current_user.user_id,
        "username": current_user.username,
        "role": current_user.role,
    }
