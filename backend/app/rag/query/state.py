"""Query graph state definition."""

from collections.abc import Mapping
from typing import Any, Required, TypedDict, cast


class QueryState(TypedDict, total=False):
    # 输入
    query: Required[str]

    # entity
    confirmed_entity: str
    entity_filter: str
    entity_mode: str              # "single" | "multi_explicit" | "broad" | "none"
    matched_entities: list[str]   # 匹配到的所有 entity
    per_entity_counts: dict       # {"entity_name": hit_count}
    alias_trace: list[dict]

    # query
    rewritten_query: str
    query_plan: dict

    # 搜索结果
    search_results: list[dict]
    search_results_hyde: list[dict]
    search_results_expanded: list[list[dict]]
    search_mode: str
    search_mode_hyde: str
    search_modes_expanded: list[str]
    expanded_queries: list[str]
    per_query_counts: dict[str, int]
    query_expansion_trace: list[dict]
    fallback_info: dict
    rerank_candidates: list[dict]
    rerank_debug: list[dict]
    context_diversify_debug: dict
    context_map: dict[str, dict]  # "C1" -> {document_id, file_title, ...}

    # 生成
    context_text: str
    answer: str
    citations: list[dict]
    trace: dict

    # groundedness
    groundedness: dict  # {enabled, status, groundedness_score, claims, warning}

    # 状态
    status: str
    error_msg: str


def _required_non_empty_str(state: Mapping[str, Any], key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing required query state field: {key}")
    return value.strip()


def require_query(state: Mapping[str, Any]) -> str:
    """Return the original user query, failing fast if query state is invalid."""
    return _required_non_empty_str(state, "query")


def require_context_text(state: Mapping[str, Any]) -> str:
    """Return prompt context, failing fast if prompt construction did not run."""
    return _required_non_empty_str(state, "context_text")


def effective_query(state: Mapping[str, Any]) -> str:
    """Prefer rewritten_query when available, otherwise require the original query."""
    rewritten = state.get("rewritten_query")
    if isinstance(rewritten, str) and rewritten.strip():
        return rewritten
    return require_query(state)


def query_state_from_mapping(
    state: Mapping[str, Any] | None = None,
    *,
    query: str | None = None,
    **updates: Any,
) -> QueryState:
    """Build a QueryState boundary object and validate the required query field."""
    data = dict(state or {})
    if query is not None:
        existing_query = state.get("query") if state else None
        if (
            isinstance(existing_query, str)
            and existing_query.strip()
            and query.strip()
            and existing_query.strip() != query.strip()
        ):
            raise ValueError("Conflicting query values in query state boundary")
        data["query"] = query
    data.update(updates)
    data["query"] = require_query(data)
    return cast(QueryState, data)
