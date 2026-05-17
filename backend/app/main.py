"""
FastAPI 应用入口模块

创建并配置 FastAPI 应用实例，包括：
- 生命周期管理（启动时初始化 LangGraph 图和数据库）
- CORS 中间件配置
- API 路由注册（统一挂载到 /api 前缀下）
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理器

    启动阶段：初始化 LangGraph 图和数据库。
    关闭阶段：执行资源清理。
    """
    # 启动时初始化 LangGraph 图和数据库
    from app.core.graph_manager import graph_manager
    from app.core.database import init_db
    from app.core.runtime_settings import runtime_settings
    await graph_manager.init()
    print("[启动] GraphManager 就绪")
    await init_db()
    await runtime_settings.get_all()  # 预加载运行时设置到内存缓存
    print("[启动] RuntimeSettings 已加载")
    yield
    print("[关闭] 服务停止")


# 创建 FastAPI 应用实例
app = FastAPI(
    title="Multimodal RAG Pro API",
    description="企业级多模态 RAG 系统后端",
    version="0.1.0",
    lifespan=lifespan,
)

# 添加 CORS 中间件，允许前端开发服务器跨域访问后端接口
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,  # 允许的前端地址列表
    allow_credentials=True,  # 允许携带 Cookie 等凭据
    allow_methods=["*"],  # 允许所有 HTTP 方法
    allow_headers=["*"],  # 允许所有请求头
)

# 将所有 API 路由挂载到 /api 前缀下
app.include_router(api_router, prefix="/api")
