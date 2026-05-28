"""Rule-based query rewrite — pronoun resolution."""

from __future__ import annotations

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import get_query_config
from app.rag.query.state import QueryState

# 代词列表，按长度降序匹配
_PRONOUNS = [
    "这家公司", "该公司", "这家企业", "该企业",
    "它的", "它的", "该公司的", "该企业的",
    "它", "其",
]


def rewrite_query_node(state: QueryState, config: RunnableConfig) -> dict:
    """规则版代词替换：single 模式下替换代词，multi/broad/none 跳过。"""
    cfg = get_query_config(config)
    if not cfg.use_rewrite:
        return {"rewritten_query": state["query"]}

    query = state["query"]

    # multi / broad / none 模式不做代词替换，避免污染
    if state.get("entity_mode", "none") != "single":
        return {"rewritten_query": query}

    entity = state.get("confirmed_entity", "")
    if not entity:
        return {"rewritten_query": query}

    rewritten = query
    for pronoun in _PRONOUNS:
        if pronoun in rewritten:
            rewritten = rewritten.replace(pronoun, entity, 1)

    return {"rewritten_query": rewritten}
