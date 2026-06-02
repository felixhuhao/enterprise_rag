"""Query stats API — GET /query/stats, /query/stats/trend, /query/stats/records."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import CurrentUser
from app.deps import verify_token
from app.services.query_stats_service import query_stats_service

router = APIRouter()


def _user_filter(user: CurrentUser, filter_user_id: str = "") -> str | None:
    """admin → None（看全部）；user → user_id."""
    if user.role == "admin":
        return filter_user_id or None
    return user.user_id


@router.get("/query/stats")
async def get_query_stats(
    filter_user_id: str = "",
    current_user: CurrentUser = Depends(verify_token),
):
    return await query_stats_service.get_stats(_user_filter(current_user, filter_user_id))


@router.get("/query/stats/trend")
async def get_query_stats_trend(
    filter_user_id: str = "",
    current_user: CurrentUser = Depends(verify_token),
):
    return await query_stats_service.get_trend(user_id=_user_filter(current_user, filter_user_id))


@router.get("/query/stats/by-flavor")
async def get_query_stats_by_flavor(
    filter_user_id: str = "",
    current_user: CurrentUser = Depends(verify_token),
):
    return await query_stats_service.get_stats_by_flavor(_user_filter(current_user, filter_user_id))


@router.get("/query/stats/by-strict")
async def get_query_stats_by_strict(
    filter_user_id: str = "",
    current_user: CurrentUser = Depends(verify_token),
):
    return await query_stats_service.get_stats_by_strict(_user_filter(current_user, filter_user_id))


@router.get("/query/stats/latency")
async def get_query_stats_latency(
    filter_user_id: str = "",
    current_user: CurrentUser = Depends(verify_token),
):
    """Latency p50/p95 grouped by flavor/status/endpoint plus stage summaries."""
    return await query_stats_service.get_latency_breakdown(_user_filter(current_user, filter_user_id))


@router.get("/query/stats/records")
async def get_query_stats_records(
    page: int = 1,
    page_size: int = 20,
    current_user: CurrentUser = Depends(verify_token),
    filter_user_id: str = "",
    flavor: str = "",
):
    """分页记录。admin 可传 filter_user_id 查看特定用户。"""
    uid = _user_filter(current_user, filter_user_id)
    return await query_stats_service.get_records(page, page_size, uid, flavor or None)


@router.get("/query/stats/records/{record_id}")
async def get_query_stats_record_detail(
    record_id: int,
    current_user: CurrentUser = Depends(verify_token),
    filter_user_id: str = "",
):
    """Fetch one query run with decoded observability details."""
    uid = _user_filter(current_user, filter_user_id)
    record = await query_stats_service.get_record_detail(record_id, uid)
    if not record:
        raise HTTPException(status_code=404, detail="query stats record not found")
    return record
