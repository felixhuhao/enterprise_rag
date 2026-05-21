"""LLM answer generation."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.rag.query.state import QueryState

_chat_llm = ChatOpenAI(
    model=settings.CHAT_MODEL,
    api_key=settings.DASHSCOPE_API_KEY,
    base_url=settings.DASHSCOPE_BASE_URL,
    timeout=settings.CHAT_TIMEOUT,
    max_retries=3,
)


def generate_answer_node(state: QueryState) -> dict:
    """调用 LLM 生成回答。citation 提取由 validate_citations 节点负责。"""
    messages = [
        SystemMessage(content=state["context_text"]),
        HumanMessage(content=state["query"]),
    ]
    response = _chat_llm.invoke(messages)
    return {"answer": response.content}
