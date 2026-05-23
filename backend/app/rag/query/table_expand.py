"""Expand table_summary hits with actual table content."""

from __future__ import annotations

import logging

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import get_query_config
from app.rag.query.search import SEARCH_TIMEOUT
from app.rag.query.state import QueryState
from app.rag.vectorstores.general_milvus import COLLECTION_NAME, client

logger = logging.getLogger(__name__)

_EXPAND_FIELDS = [
    "content",
    "title",
    "section_title",
    "source_type",
    "table_id",
    "table_tokens",
    "raw_table_path",
    "document_id",
    "file_title",
    "entity_name",
    "part",
    "chunk_id",
]


def table_expand_node(state: QueryState, config: RunnableConfig) -> dict:
    """把 table_summary 替换为 table_full / table_row_group。"""
    cfg = get_query_config(config)
    if not cfg.use_table_expand:
        return {"search_results": state.get("search_results", [])}

    results = state.get("search_results", [])
    if not results:
        return {"search_results": [], "status": "expanded"}

    expanded: list[dict] = []

    for hit in results:
        if hit.get("source_type") != "table_summary":
            expanded.append(hit)
            continue

        table_id = hit.get("table_id", "")
        if not table_id:
            expanded.append(hit)
            continue

        tokens = hit.get("table_tokens") or 0
        target_type = "table_full" if tokens <= cfg.table_full_token_limit else "table_row_group"

        try:
            rows = client.query(
                collection_name=COLLECTION_NAME,
                filter=f'table_id == "{table_id}" and source_type == "{target_type}"',
                output_fields=_EXPAND_FIELDS,
                limit=cfg.table_expand_limit,
                timeout=SEARCH_TIMEOUT,
            )
        except Exception:
            logger.warning("table_expand query failed for %s", table_id, exc_info=True)
            expanded.append(hit)
            continue

        if not rows:
            expanded.append(hit)
            continue

        for row in rows:
            expanded.append({
                "chunk_id": row.get("chunk_id"),
                "document_id": row.get("document_id", ""),
                "file_title": row.get("file_title", ""),
                "title": row.get("title", ""),
                "section_title": row.get("section_title", ""),
                "source_type": row.get("source_type", ""),
                "table_id": row.get("table_id", ""),
                "table_tokens": row.get("table_tokens"),
                "raw_table_path": row.get("raw_table_path", ""),
                "content": row.get("content", ""),
                "part": row.get("part"),
                "score": hit.get("score", 0),
            })

        logger.debug("Expanded table %s → %d %s chunks", table_id, len(rows), target_type)

    return {"search_results": expanded}
