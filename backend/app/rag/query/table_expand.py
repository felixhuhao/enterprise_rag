"""Expand table_summary hits with actual table content."""

from __future__ import annotations

import logging

from langgraph.graph.state import RunnableConfig

from app.rag.chunking.chunk_keys import base_chunk_key
from app.rag.query.config import get_query_config
from app.rag.query.search import SEARCH_TIMEOUT
from app.rag.query.state import QueryState
from app.rag.vectorstores.general_milvus import COLLECTION_NAME, available_output_fields, client

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
    "page",
    "file_title",
    "entity_name",
    "part",
    "chunk_id",
    "chunk_key",
    "table_title",
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
        doc_id = hit.get("document_id", "")

        try:
            filter_expr = f'table_id == "{table_id}" and source_type == "{target_type}"'
            if doc_id:
                filter_expr += f' and document_id == "{doc_id}"'
            rows = client.query(
                collection_name=COLLECTION_NAME,
                filter=filter_expr,
                output_fields=available_output_fields(_EXPAND_FIELDS),
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

        base_paths = hit.get("retrieval_paths") or []
        if not base_paths and hit.get("retrieval_path"):
            base_paths = [hit["retrieval_path"]]
        retrieval_paths = [*base_paths, "table_expand"]

        for row in rows:
            expanded.append({
                "chunk_id": row.get("chunk_id"),
                "chunk_key": row.get("chunk_key") or _fallback_chunk_key(row),
                "document_id": row.get("document_id", ""),
                "page": row.get("page"),
                "file_title": row.get("file_title", ""),
                "entity_name": row.get("entity_name", ""),
                "title": row.get("title", ""),
                "section_title": row.get("section_title", ""),
                "source_type": row.get("source_type", ""),
                "table_id": row.get("table_id", ""),
                "table_title": row.get("table_title", ""),
                "table_tokens": row.get("table_tokens"),
                "raw_table_path": row.get("raw_table_path", ""),
                "content": row.get("content", ""),
                "part": row.get("part"),
                "score": hit.get("score", 0),
                "retrieval_paths": retrieval_paths,
                "retrieval_path": " + ".join(retrieval_paths),
            })

        logger.debug("Expanded table %s → %d %s chunks", table_id, len(rows), target_type)

    return {"search_results": expanded}


def _fallback_chunk_key(row: dict) -> str:
    return base_chunk_key({
        "document_id": row.get("document_id", ""),
        "source_type": row.get("source_type", ""),
        "table_id": row.get("table_id", ""),
        "section_title": row.get("section_title", ""),
        "part": row.get("part"),
        "content": row.get("content", ""),
    })
