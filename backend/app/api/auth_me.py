"""Current user info — GET /api/me."""

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, user_entities
from app.deps import verify_token

router = APIRouter()


@router.get("/me")
async def get_me(current_user: CurrentUser = Depends(verify_token)):
    write_entities = (
        None
        if current_user.role == "admin"
        else await user_entities(current_user, min_permission="write")
    )
    return {
        "user_id": current_user.user_id,
        "username": current_user.username,
        "role": current_user.role,
        "write_entities": write_entities,
    }
