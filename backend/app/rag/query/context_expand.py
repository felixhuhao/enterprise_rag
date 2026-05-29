"""Expand final text anchors with neighboring chunks for prompt context."""

from __future__ import annotations

import logging

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import get_query_config
from app.rag.query.filter_utils import escape_milvus_string
from app.rag.query.search import SEARCH_TIMEOUT
from app.rag.query.state import QueryState
from app.rag.vectorstores.general_milvus import COLLECTION_NAME, available_output_fields, client

logger = logging.getLogger(__name__)

_EXPAND_FIELDS = ["chunk_id", "chunk_key", "content", "part", "section_title"]


def context_expand_node(state: QueryState, config: RunnableConfig) -> dict:
    """Small-to-big expansion after rerank, preserving anchor chunk ids."""
    cfg = get_query_config(config)
    results = state.get("search_results", [])
    if not cfg.use_context_expand:
        return {"search_results": results}
    if not results:
        return {"search_results": []}

    max_chars = int(cfg.context_expand_max_chars)
    window = int(cfg.context_expand_window)
    if window <= 0:
        return {"search_results": results}

    expanded_results = [dict(row) for row in results]
    anchor_chunk_ids = {row.get("chunk_id") for row in expanded_results if row.get("chunk_id") is not None}
    anchor_chunk_keys = {row.get("chunk_key") for row in expanded_results if row.get("chunk_key")}
    groups: dict[tuple[str, str], dict] = {}

    for idx, row in enumerate(expanded_results):
        anchor = _anchor_info(row, cfg.context_expand_same_section, max_chars)
        if anchor is None:
            continue
        group_key, part = anchor
        group = groups.setdefault(group_key, {"anchors": [], "parts": set(), "anchor_parts": set()})
        group["anchors"].append((idx, part))
        group["anchor_parts"].add(part)
        for neighbor_part in range(max(1, part - window), part + window + 1):
            if neighbor_part != part:
                group["parts"].add(neighbor_part)

    if not groups:
        return {"search_results": expanded_results}

    neighbors_by_group: dict[tuple[str, str], dict[int, dict]] = {}
    for group_key, group in groups.items():
        parts = sorted(p for p in group["parts"] if p not in group["anchor_parts"])
        if not parts:
            continue
        rows = _query_neighbors(group_key, parts, same_section=cfg.context_expand_same_section)
        if not rows:
            continue
        by_part: dict[int, dict] = {}
        for row in rows:
            part = _int_part(row.get("part"))
            if part is None or row.get("chunk_id") in anchor_chunk_ids or row.get("chunk_key") in anchor_chunk_keys:
                continue
            by_part[part] = row
        neighbors_by_group[group_key] = by_part

    for group_key, group in groups.items():
        neighbors = neighbors_by_group.get(group_key) or {}
        if not neighbors:
            continue
        for idx, part in group["anchors"]:
            row = expanded_results[idx]
            left = [neighbors[p] for p in range(part - window, part) if p in neighbors]
            right = [neighbors[p] for p in range(part + 1, part + window + 1) if p in neighbors]
            if not left and not right:
                continue
            _expand_anchor(row, left, right, max_chars)

    return {"search_results": expanded_results}


def _anchor_info(row: dict, same_section: bool, max_chars: int) -> tuple[tuple[str, str], int] | None:
    if row.get("source_type") != "text":
        return None
    if len(str(row.get("content") or "")) > max_chars:
        return None

    doc_id = str(row.get("document_id") or "")
    if not doc_id:
        return None

    section = str(row.get("section_title") or "")
    if same_section and not section:
        return None

    part = _int_part(row.get("part"))
    if part is None or part <= 0:
        return None

    return (doc_id, section if same_section else ""), part


def _query_neighbors(group_key: tuple[str, str], parts: list[int], *, same_section: bool) -> list[dict]:
    doc_id, section = group_key
    part_expr = ", ".join(str(p) for p in parts)
    filter_expr = (
        f'document_id == "{escape_milvus_string(doc_id)}" '
        f"and part in [{part_expr}] "
        'and source_type == "text"'
    )
    if same_section:
        filter_expr = (
            f'document_id == "{escape_milvus_string(doc_id)}" '
            f'and section_title == "{escape_milvus_string(section)}" '
            f"and part in [{part_expr}] "
            'and source_type == "text"'
        )

    try:
        rows = client.query(
            collection_name=COLLECTION_NAME,
            filter=filter_expr,
            output_fields=available_output_fields(_EXPAND_FIELDS),
            limit=max(len(parts) * 4, 10),
            timeout=SEARCH_TIMEOUT,
        )
    except Exception:
        logger.warning("context_expand query failed for document_id=%s section=%s", doc_id, section, exc_info=True)
        return []
    return rows or []


def _expand_anchor(row: dict, left: list[dict], right: list[dict], max_chars: int):
    original = str(row.get("content") or "")
    if len(original) > max_chars:
        return

    remaining = max_chars - len(original)
    if remaining <= 0:
        return

    left_text = "\n\n".join(str(n.get("content") or "") for n in left)
    right_text = "\n\n".join(str(n.get("content") or "") for n in right)
    left_budget = remaining // 2 if right_text else remaining
    right_budget = remaining - left_budget if left_text else remaining

    left_text = _tail(left_text, left_budget)
    right_text = _head(right_text, right_budget)
    pieces = [text for text in (left_text, original, right_text) if text]
    if len(pieces) <= 1:
        return

    row["content"] = "\n\n".join(pieces)[:max_chars]
    row["context_expanded_chunk_ids"] = [
        n.get("chunk_id")
        for n in [*left, *right]
        if n.get("chunk_id") is not None
    ]
    row["context_expand_parts"] = [
        n.get("part")
        for n in [*left, *right]
        if n.get("part") is not None
    ]

    base_paths = row.get("retrieval_paths") or []
    if not base_paths and row.get("retrieval_path"):
        base_paths = [row["retrieval_path"]]
    if "context_expand" not in base_paths:
        row["retrieval_paths"] = [*base_paths, "context_expand"]
        row["retrieval_path"] = " + ".join(row["retrieval_paths"])


def _int_part(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _head(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    return text[:limit]


def _tail(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    return text[-limit:]
