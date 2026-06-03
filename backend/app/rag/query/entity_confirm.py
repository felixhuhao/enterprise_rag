"""Entity confirmation node with canonical entity and alias matching."""

from __future__ import annotations

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import get_query_config
from app.rag.query.filter_utils import build_entity_expr
from app.rag.query.state import QueryState, require_query

_BROAD_SIGNALS = [
    "所有公司", "所有企业", "全部公司", "全部企业",
    "哪些公司", "哪些企业", "各公司", "各企业",
    "整体", "全部", "各家", "每家公司", "每家企业",
    "所有实体", "全部实体", "各个公司",
]


def entity_confirm_node(state: QueryState, config: RunnableConfig) -> dict:
    """Match explicit canonical entities first, then unambiguous aliases."""
    cfg = get_query_config(config)
    if not cfg.use_entity_confirm:
        return _empty_result("none")

    query = require_query(state)
    from app.rag.query.entity_cache import get_alias_map, get_known_entities

    known = get_known_entities()
    alias_map = get_alias_map()

    matched: list[str] = []
    remaining = query

    for name in sorted(known, key=len, reverse=True):
        if name in remaining:
            matched.append(name)
            remaining = remaining.replace(name, "", 1)

    alias_trace: list[dict] = []
    for alias in sorted(alias_map.keys(), key=len, reverse=True):
        if not _contains_casefold(remaining, alias):
            continue
        canonicals = alias_map[alias]
        if len(canonicals) == 1:
            canonical = canonicals[0]
            if canonical not in matched:
                matched.append(canonical)
            alias_trace.append({
                "alias": alias,
                "canonical": canonical,
                "ambiguous": False,
            })
        else:
            alias_trace.append({
                "alias": alias,
                "canonicals": canonicals,
                "ambiguous": True,
            })
        remaining = _remove_first_casefold(remaining, alias)

    matched = list(dict.fromkeys(matched))
    if not matched:
        mode = "broad" if _has_broad_signal(query) else "none"
        result = _empty_result(mode)
        result["alias_trace"] = alias_trace
        return result

    if len(matched) == 1:
        entity = matched[0]
        return {
            "confirmed_entity": entity,
            "entity_filter": build_entity_expr(entity),
            "entity_mode": "single",
            "matched_entities": [entity],
            "per_entity_counts": {},
            "alias_trace": alias_trace,
        }

    return {
        "confirmed_entity": matched[0],
        "entity_filter": "",
        "entity_mode": "multi_explicit",
        "matched_entities": matched,
        "per_entity_counts": {},
        "alias_trace": alias_trace,
    }


def _empty_result(mode: str) -> dict:
    return {
        "confirmed_entity": "",
        "entity_filter": "",
        "entity_mode": mode,
        "matched_entities": [],
        "per_entity_counts": {},
        "alias_trace": [],
    }


def _has_broad_signal(query: str) -> bool:
    return any(sig in query for sig in _BROAD_SIGNALS)


def _contains_casefold(text: str, needle: str) -> bool:
    return needle.casefold() in text.casefold()


def _remove_first_casefold(text: str, needle: str) -> str:
    start = text.casefold().find(needle.casefold())
    if start < 0:
        return text
    return text[:start] + text[start + len(needle):]
