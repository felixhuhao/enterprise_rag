"""
API 路由聚合模块

将所有子模块的 APIRouter 实例统一注册到一个聚合路由器中，
由 main.py 挂载到 FastAPI 应用的 /api 前缀下。
"""

from fastapi import APIRouter

from app.api.settings_api import router as settings_router
from app.api.documents import router as documents_router
from app.api.query_chat import router as query_chat_router
from app.api.query_stats import router as query_stats_router

# 创建聚合路由器
api_router = APIRouter()

api_router.include_router(settings_router, tags=["settings"])
api_router.include_router(documents_router, tags=["documents"])
api_router.include_router(query_chat_router, tags=["query"])
api_router.include_router(query_stats_router, tags=["query-stats"])
