"""
API 路由聚合模块

将所有子模块的 APIRouter 实例统一注册到一个聚合路由器中，
由 main.py 挂载到 FastAPI 应用的 /api 前缀下。
"""

from fastapi import APIRouter

from app.api.settings_api import router as settings_router
from app.api.evaluate import router as evaluate_router
from app.api.documents import router as documents_router
from app.api.query_chat import router as query_chat_router

# 创建聚合路由器
api_router = APIRouter()

# 旧 chat/approval/session 路由依赖 graph/workflow（segfault），暂时禁用
# from app.api.chat import router as chat_router
# from app.api.approval import router as approval_router
# from app.api.sessions import router as sessions_router
# api_router.include_router(chat_router, tags=["chat"])
# api_router.include_router(approval_router, tags=["approval"])
# api_router.include_router(sessions_router, tags=["sessions"])

api_router.include_router(settings_router, tags=["settings"])
api_router.include_router(evaluate_router, tags=["evaluate"])
api_router.include_router(documents_router, tags=["documents"])
api_router.include_router(query_chat_router, tags=["query"])
