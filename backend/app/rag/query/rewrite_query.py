"""Rule-based query rewrite — pronoun resolution."""

from __future__ import annotations

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import get_query_config
from app.rag.query.state import QueryState, require_query

# Explicit entity pronouns only. Avoid bare "其"/"它": both are too common in
# ordinary Chinese words and can corrupt queries such as "其中".
_PRONOUN_REPLACEMENTS = (
    ("该公司的", "{entity}的"),
    ("该企业的", "{entity}的"),
    ("它的", "{entity}的"),
    ("这家公司", "{entity}"),
    ("该公司", "{entity}"),
    ("这家企业", "{entity}"),
    ("该企业", "{entity}"),
)


def rewrite_query_node(state: QueryState, config: RunnableConfig) -> dict:
    """规则版代词替换：single 模式下替换代词，multi/broad/none 跳过。"""
    cfg = get_query_config(config)
    query = require_query(state)
    if not cfg.use_rewrite:
        return {"rewritten_query": query}

    # multi / broad / none 模式不做代词替换，避免污染
    if state.get("entity_mode", "none") != "single":
        return {"rewritten_query": query}

    entity = state.get("confirmed_entity", "")
    if not entity:
        return {"rewritten_query": query}

    rewritten = query
    for pronoun, replacement in _PRONOUN_REPLACEMENTS:
        if pronoun in rewritten:
            rewritten = rewritten.replace(pronoun, replacement.format(entity=entity), 1)

    return {"rewritten_query": rewritten}
