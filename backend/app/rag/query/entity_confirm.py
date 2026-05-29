"""Entity confirmation node — match known entity_names from query text.

Supports multi-entity routing:
- single: exactly one entity matched (backward compatible)
- multi_explicit: 2+ entities matched → per-entity retrieval
- broad: no match + broad-signal keywords → global retrieval
- none: no match, no broad signal → global retrieval (same as broad for now)
"""

from __future__ import annotations

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import QueryConfig, get_query_config
from app.rag.query.filter_utils import build_entity_expr
from app.rag.query.state import QueryState

_BROAD_SIGNALS = [
    "所有公司", "所有企业", "全部公司", "全部企业",
    "哪些公司", "哪些企业", "各公司", "各企业",
    "整体", "全部", "各家", "每家公司", "每家企业",
    "所有实体", "全部实体", "各个公司",
]


def entity_confirm_node(state: QueryState, config: RunnableConfig) -> dict:
    """从已知列表匹配 entity_name，返回单/多/全局模式。"""
    cfg = get_query_config(config)
    if not cfg.use_entity_confirm:
        return {
            "confirmed_entity": "",
            "entity_filter": "",
            "entity_mode": "none",
            "matched_entities": [],
            "per_entity_counts": {},
        }

    query = state["query"]
    from app.rag.query.entity_cache import get_known_entities

    known = get_known_entities()

    # 匹配所有已知 entity（贪心最长优先，从 query 中逐个移除避免重叠）
    matched: list[str] = []
    remaining = query
    for name in sorted(known, key=len, reverse=True):
        if name in remaining:
            matched.append(name)
            remaining = remaining.replace(name, "", 1)

    if not matched:
        # 无匹配 → 判断 broad 信号
        mode = "broad" if _has_broad_signal(query) else "none"
        return {
            "confirmed_entity": "",
            "entity_filter": "",
            "entity_mode": mode,
            "matched_entities": [],
            "per_entity_counts": {},
        }

    if len(matched) == 1:
        # 单 entity — 完全保持现有行为
        entity = matched[0]
        return {
            "confirmed_entity": entity,
            "entity_filter": build_entity_expr(entity),
            "entity_mode": "single",
            "matched_entities": [entity],
            "per_entity_counts": {},
        }

    # 多 entity — confirmed_entity 取最长（兼容旧 UI），filter 设空
    return {
        "confirmed_entity": matched[0],
        "entity_filter": "",
        "entity_mode": "multi_explicit",
        "matched_entities": matched,
        "per_entity_counts": {},
    }


def _has_broad_signal(query: str) -> bool:
    return any(sig in query for sig in _BROAD_SIGNALS)
