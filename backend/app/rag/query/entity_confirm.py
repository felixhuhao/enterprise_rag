"""Entity confirmation node — match known entity_name from query text."""

from __future__ import annotations

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import QueryConfig, get_query_config
from app.rag.query.entity_cache import get_known_entities
from app.rag.query.state import QueryState


def entity_confirm_node(state: QueryState, config: RunnableConfig) -> dict:
    """从已知列表匹配 entity_name，置信度分层。"""
    cfg = get_query_config(config)
    if not cfg.use_entity_confirm:
        return {"confirmed_entity": "", "entity_filter": ""}

    query = state["query"]
    known = get_known_entities()

    matched: list[str] = []
    remaining = query
    for name in sorted(known, key=len, reverse=True):
        if name in remaining:
            matched.append(name)
            remaining = remaining.replace(name, "", 1)

    if matched:
        confirmed = matched[0]  # 取最长的
        entity_filter = f'entity_name == "{confirmed}"'
    else:
        confirmed = ""
        entity_filter = ""

    return {
        "confirmed_entity": confirmed,
        "entity_filter": entity_filter,
    }
