"""
FastAPI 应用入口模块

创建并配置 FastAPI 应用实例，包括：
- 生命周期管理（启动时初始化 LangGraph 图和数据库）
- CORS 中间件配置
- API 路由注册（统一挂载到 /api 前缀下）
"""

from contextlib import asynccontextmanager
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.api.router import api_router

_rate_limit_windows: dict[str, tuple[int, int]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理器

    启动阶段：初始化 LangGraph 图和数据库。
    关闭阶段：执行资源清理。
    """
    # 启动时初始化数据库
    from app.core.database import init_db
    from app.core.runtime_settings import runtime_settings
    from app.services.document_service import mark_interrupted_documents_failed
    from app.services.job_service import mark_interrupted_jobs_failed
    await init_db()
    await mark_interrupted_jobs_failed()
    await mark_interrupted_documents_failed()
    await runtime_settings.get_all()  # 预加载运行时设置到内存缓存
    print("[启动] RuntimeSettings 已加载")
    yield
    print("[关闭] 服务停止")


# 创建 FastAPI 应用实例
app = FastAPI(
    title="Enterprise RAG Platform API",
    description="Enterprise document RAG backend with text-first multimodal ingestion",
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


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    limit = int(settings.RATE_LIMIT_PER_MINUTE or 0)
    if limit <= 0 or not request.url.path.startswith("/api/"):
        return await call_next(request)

    token = request.headers.get("authorization", "")
    client_host = request.client.host if request.client else "unknown"
    key = token or client_host
    window = int(time.monotonic() // 60)
    current_window, count = _rate_limit_windows.get(key, (window, 0))
    if current_window != window:
        current_window, count = window, 0
    count += 1
    _rate_limit_windows[key] = (current_window, count)

    if count > limit:
        return JSONResponse(
            status_code=429,
            content={"detail": "请求过于频繁，请稍后再试"},
            headers={"Retry-After": "60"},
        )
    return await call_next(request)

# 健康检查（不需要鉴权）
@app.get("/health")
async def health():
    return {"status": "ok"}

# 将所有 API 路由挂载到 /api 前缀下
app.include_router(api_router, prefix="/api")
