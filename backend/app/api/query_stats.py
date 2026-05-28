"""Query stats API — GET /query/stats, /query/stats/trend, /query/stats/records."""

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser
from app.deps import verify_token
from app.services.query_stats_service import query_stats_service

router = APIRouter()


def _user_filter(user: CurrentUser) -> str | None:
    """admin → None（看全部）；user → user_id."""
    return None if user.role == "admin" else user.user_id


@router.get("/query/stats")
async def get_query_stats(current_user: CurrentUser = Depends(verify_token)):
    return await query_stats_service.get_stats(_user_filter(current_user))


@router.get("/query/stats/trend")
async def get_query_stats_trend(current_user: CurrentUser = Depends(verify_token)):
    return await query_stats_service.get_trend(user_id=_user_filter(current_user))


@router.get("/query/stats/records")
async def get_query_stats_records(
    page: int = 1,
    page_size: int = 20,
    current_user: CurrentUser = Depends(verify_token),
):
    return await query_stats_service.get_records(page, page_size, _user_filter(current_user))
