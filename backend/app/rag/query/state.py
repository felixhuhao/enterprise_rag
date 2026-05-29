"""Query graph state definition."""

from typing import TypedDict


class QueryState(TypedDict, total=False):
    # 输入
    query: str

    # entity
    confirmed_entity: str
    entity_filter: str
    entity_mode: str              # "single" | "multi_explicit" | "broad" | "none"
    matched_entities: list[str]   # 匹配到的所有 entity
    per_entity_counts: dict       # {"entity_name": hit_count}

    # query
    rewritten_query: str
    query_plan: dict

    # 搜索结果
    search_results: list[dict]
    search_results_hyde: list[dict]
    search_mode: str
    search_mode_hyde: str
    fallback_info: dict
    rerank_debug: list[dict]
    context_map: dict[str, dict]  # "C1" -> {document_id, file_title, ...}

    # 生成
    context_text: str
    answer: str
    citations: list[dict]

    # groundedness
    groundedness: dict  # {enabled, status, groundedness_score, claims, warning}

    # 状态
    status: str
    error_msg: str
