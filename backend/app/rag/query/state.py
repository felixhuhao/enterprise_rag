"""Query graph state definition."""

from typing import TypedDict


class QueryState(TypedDict, total=False):
    # 输入
    query: str

    # entity
    confirmed_entity: str
    entity_filter: str

    # query
    rewritten_query: str

    # 搜索结果
    search_results: list[dict]
    search_results_hyde: list[dict]
    context_map: dict[str, dict]  # "C1" -> {document_id, file_title, ...}

    # 生成
    context_text: str
    answer: str
    citations: list[dict]

    # 状态
    status: str
    error_msg: str
