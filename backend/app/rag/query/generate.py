"""LLM answer generation."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.rag.query.state import QueryState, require_context_text, require_query
from app.utils.llm_usage import extract_llm_token_usage, llm_model_name

_chat_llm = ChatOpenAI(
    model=settings.CHAT_MODEL,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    timeout=settings.CHAT_TIMEOUT,
    max_retries=3,
    temperature=settings.CHAT_TEMPERATURE,
    max_tokens=settings.CHAT_MAX_TOKENS,
)


def generate_answer_node(state: QueryState) -> dict:
    """调用 LLM 生成回答。citation 提取由 validate_citations 节点负责。"""
    messages = [
        SystemMessage(content=require_context_text(state)),
        HumanMessage(content=require_query(state)),
    ]
    response = _chat_llm.invoke(messages)
    return {
        "answer": response.content,
        "token_usage": extract_llm_token_usage(response, llm_model_name(_chat_llm)),
    }
