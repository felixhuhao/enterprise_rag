"""Query stats API — GET /query/stats, /query/stats/trend, /query/stats/records."""

from fastapi import APIRouter, Depends

from app.deps import verify_token
from app.services.query_stats_service import query_stats_service

router = APIRouter()


@router.get("/query/stats")
async def get_query_stats(_: None = Depends(verify_token)):
    return await query_stats_service.get_stats()


@router.get("/query/stats/trend")
async def get_query_stats_trend(_: None = Depends(verify_token)):
    return await query_stats_service.get_trend()


@router.get("/query/stats/records")
async def get_query_stats_records(
    page: int = 1,
    page_size: int = 20,
    _: None = Depends(verify_token),
):
    return await query_stats_service.get_records(page, page_size)
