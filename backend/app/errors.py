"""Application error codes — structured error types for ingestion and query."""

from __future__ import annotations

from collections.abc import Iterable
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
    chain = tuple(_exception_chain(exc))

    if any(_matches(err, ("mineru",)) for err in chain):
        return AppErrorCode.MINERU_API_ERROR

    if any(_matches(err, ("embedding", "embeddings", "embed")) for err in chain):
        return AppErrorCode.EMBEDDING_ERROR

    if any(_is_milvus_error(err) for err in chain):
        return AppErrorCode.MILVUS_ERROR

    if any(_is_llm_error(err) for err in chain):
        return AppErrorCode.LLM_ERROR

    return AppErrorCode.UNKNOWN_ERROR


def _exception_chain(exc: BaseException) -> Iterable[BaseException]:
    """Yield an exception plus its explicit/implicit causes once."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _error_text(err: BaseException) -> str:
    cls = type(err)
    return " ".join((
        cls.__module__,
        cls.__name__,
        str(err),
    )).lower()


def _matches(err: BaseException, needles: tuple[str, ...]) -> bool:
    text = _error_text(err)
    return any(needle in text for needle in needles)


def _is_milvus_error(err: BaseException) -> bool:
    cls = type(err)
    module = cls.__module__.lower()
    if module.startswith(("pymilvus", "milvus")):
        return True
    return _matches(err, ("milvus", "pymilvus"))


def _is_llm_error(err: BaseException) -> bool:
    cls = type(err)
    module = cls.__module__.lower()
    if module.startswith(("openai", "langchain_openai", "dashscope")):
        return True
    return _matches(err, ("openai", "dashscope", "deepseek", "chatopenai", "llm"))
