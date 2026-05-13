"""
评估看板 API 端点模块

端点：
- GET /evaluate/stats: 聚合统计数据
- GET /evaluate/distribution: 分数分箱分布
- GET /evaluate/trend: 每日平均分趋势
- GET /evaluate/records: 分页评估记录
"""

from fastapi import APIRouter, Depends

from app.deps import verify_token
from app.services.evaluate_service import evaluate_service

router = APIRouter()


@router.get("/evaluate/stats")
async def get_stats(_: None = Depends(verify_token)):
    """获取评估统计数据"""
    return await evaluate_service.get_stats()


@router.get("/evaluate/distribution")
async def get_distribution(_: None = Depends(verify_token)):
    """获取分数分布（分箱直方图数据）"""
    return await evaluate_service.get_distribution()


@router.get("/evaluate/trend")
async def get_trend(_: None = Depends(verify_token)):
    """获取每日平均分趋势"""
    return await evaluate_service.get_trend()


@router.get("/evaluate/records")
async def get_records(
    page: int = 1,
    page_size: int = 20,
    _: None = Depends(verify_token),
):
    """获取分页评估记录"""
    return await evaluate_service.get_records(page=page, page_size=page_size)
