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
from app.api.retrieval_test import router as retrieval_test_router
from app.api.auth import router as auth_router
from app.api.auth_me import router as auth_me_router
from app.api.admin_users import router as admin_users_router
from app.api.admin_jobs import router as admin_jobs_router
from app.api.query_feedback import router as query_feedback_router
from app.api.admin_eval import router as admin_eval_router
from app.api.entity_aliases import router as entity_aliases_router
from app.api.system_info import router as system_info_router
from app.api.structured_tags import router as structured_tags_router

# 创建聚合路由器
api_router = APIRouter()

api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(auth_me_router, tags=["auth"])
api_router.include_router(admin_users_router, tags=["admin"])
api_router.include_router(admin_jobs_router, tags=["admin"])
api_router.include_router(settings_router, tags=["settings"])
api_router.include_router(documents_router, tags=["documents"])
api_router.include_router(query_chat_router, tags=["query"])
api_router.include_router(query_stats_router, tags=["query-stats"])
api_router.include_router(retrieval_test_router, tags=["retrieval-test"])
api_router.include_router(query_feedback_router, tags=["query-feedback"])
api_router.include_router(admin_eval_router, tags=["admin"])
api_router.include_router(entity_aliases_router, tags=["admin"])
api_router.include_router(structured_tags_router, tags=["admin"])
api_router.include_router(system_info_router, tags=["system"])
