"""Application error codes — structured error types for ingestion and query."""

from __future__ import annotations

from enum import Enum


class AppErrorCode(str, Enum):
    """统一错误码。"""

    # External services
    MINERU_API_ERROR = "MINERU_API_ERROR"
    EMBEDDING_ERROR = "EMBEDDING_ERROR"
    MILVUS_ERROR = "MILVUS_ERROR"
    LLM_ERROR = "LLM_ERROR"

    # Business logic
    NO_CONTEXT_FOUND = "NO_CONTEXT_FOUND"

    # Catch-all
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


# 前端展示建议（中文）
HUMAN_HINTS: dict[AppErrorCode, str] = {
    AppErrorCode.MINERU_API_ERROR: "文档解析服务异常，请稍后重试",
    AppErrorCode.EMBEDDING_ERROR: "向量化服务异常，请稍后重试",
    AppErrorCode.MILVUS_ERROR: "向量数据库异常，请检查 Milvus 连接",
    AppErrorCode.LLM_ERROR: "大模型服务异常，请稍后重试",
    AppErrorCode.NO_CONTEXT_FOUND: "未找到相关内容，请尝试换个表述或上传更多文档",
    AppErrorCode.UNKNOWN_ERROR: "未知错误，请查看详情或联系管理员",
}


def classify_error(exc: Exception) -> AppErrorCode:
    """从异常类型推断错误码。"""
    msg = str(exc).lower()
    exc_type = type(exc).__name__.lower()

    # MinerU
    if "mineru" in msg or "mineru" in exc_type:
        return AppErrorCode.MINERU_API_ERROR

    # Embedding
    if any(k in msg for k in ("embedding", "embed", "embeddings")) or "embedding" in exc_type:
        return AppErrorCode.EMBEDDING_ERROR

    # Milvus
    if "milvus" in msg or "pymilvus" in exc_type:
        return AppErrorCode.MILVUS_ERROR

    # LLM (DashScope / OpenAI compatible)
    if any(k in msg for k in ("dashscope", "openai", "llm", "chat", "timeout")):
        return AppErrorCode.LLM_ERROR

    return AppErrorCode.UNKNOWN_ERROR
