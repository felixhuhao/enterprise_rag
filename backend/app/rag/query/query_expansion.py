"""LLM query expansion for the recall retrieval flavor."""

from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.state import RunnableConfig

from app.config import settings
from app.rag.query.config import get_query_config
from app.rag.query.planner import get_query_plan
from app.rag.query.state import QueryState

logger = logging.getLogger(__name__)

EXPANSION_PROMPT = """\
根据以下企业文档检索问题，生成 {count} 条不同表述的检索查询。
要求：
1. 使用同义词、相关术语、不同角度重新表述
2. 保留关键实体名称和数值不变
3. 每条查询独立成行，不要编号
4. 不要解释，只输出查询

原始问题：{query}
"""

_numbering_re = re.compile(r"^\s*(?:[-*]\s*)?(?:\d+|[一二三四五六七八九十]+)[\.、\)\uff09]\s*")

_expansion_llm = ChatOpenAI(
    model=settings.CHAT_MODEL,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    timeout=30,
    max_retries=2,
    temperature=0.3,
)


def query_expansion_node(state: QueryState, config: RunnableConfig) -> dict:
    """Generate alternate search queries when the active query plan enables it."""
    cfg = get_query_config(config)
    plan = get_query_plan(state, config)
    if not plan.get("use_query_expansion"):
        return {"expanded_queries": []}

    query = state.get("rewritten_query") or state["query"]
    count = cfg.query_expansion_count
    try:
        response = _invoke_expansion_llm([
            HumanMessage(content=EXPANSION_PROMPT.format(query=query, count=count))
        ])
    except Exception:
        logger.warning("Query expansion LLM call failed, returning empty", exc_info=True)
        return {"expanded_queries": []}

    expanded = _parse_expanded_queries(str(response.content or ""), query, count)
    return {"expanded_queries": expanded}


def _parse_expanded_queries(content: str, original_query: str, count: int) -> list[str]:
    """Clean model output into unique query lines."""
    original_norm = _normalize_query(original_query)
    seen = {original_norm} if original_norm else set()
    out: list[str] = []
    for raw in content.splitlines():
        line = _numbering_re.sub("", raw).strip()
        if not line:
            continue
        norm = _normalize_query(line)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(line)
        if len(out) >= count:
            break
    return out


def _normalize_query(query: str) -> str:
    return " ".join(query.split()).casefold()


def _invoke_expansion_llm(messages: list[HumanMessage]):
    return _expansion_llm.invoke(messages)
