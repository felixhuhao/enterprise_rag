"""Formatting helpers for retrieval-test responses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.rag.query.config import QueryConfig


def format_result(row: dict, rank: int, *, use_rerank: bool) -> dict:
    rerank = row.get("rerank") or {}
    content = row.get("content", "") or ""
    return {
        "rank": rank,
        "chunk_id": row.get("chunk_id"),
        "chunk_key": row.get("chunk_key", ""),
        "document_id": row.get("document_id", ""),
        "file_title": row.get("file_title", ""),
        "entity_name": row.get("entity_name", ""),
        "section_title": row.get("section_title", "") or row.get("title", ""),
        "page": row.get("page"),
        "source_type": row.get("source_type", ""),
        "keywords": row.get("keywords", []),
        "structured_tags": row.get("structured_tags", []),
        "table_id": row.get("table_id", ""),
        "table_title": row.get("table_title", ""),
        "score": round(float(row.get("score", 0) or 0), 4),
        "llm_score": rerank.get("llm_score") if use_rerank else None,
        "rrf_score": rerank.get("rrf_score") if use_rerank else None,
        "final_score": rerank.get("final_score") if use_rerank else None,
        "retrieval_path": row.get("retrieval_path", "未知"),
        "retrieval_paths": row.get("retrieval_paths", []),
        "context_expanded_chunk_ids": row.get("context_expanded_chunk_ids", []),
        "context_expand_parts": row.get("context_expand_parts", []),
        "content": content,
        "content_preview": content[:500],
    }


def strategy_summary(
    cfg: QueryConfig,
    use_hybrid: bool,
    state: dict,
    *,
    settings_obj: Any,
    embedding_model_label: str,
) -> dict:
    search_mode = state.get("search_mode", "")
    hyde_mode = state.get("search_mode_hyde", "")
    expanded_modes = state.get("search_modes_expanded", []) or []
    fallback_info = state.get("fallback_info", {}) or {}
    return {
        "top_k": cfg.rerank_max_top_k,
        "hybrid": use_hybrid,
        "hyde": bool(state.get("query_plan", {}).get("use_hyde", cfg.use_hyde)),
        "query_expansion": bool(state.get("query_plan", {}).get("use_query_expansion", False)),
        "rerank": cfg.use_rerank,
        "table_expand": cfg.use_table_expand,
        "fallback": bool(fallback_info.get("used"))
        or "fallback" in search_mode
        or "fallback" in hyde_mode
        or any("fallback" in mode for mode in expanded_modes),
        "search_mode": search_mode,
        "search_mode_hyde": hyde_mode,
        "retrieval_flavor": state.get("query_plan", {}).get("retrieval_flavor", "balanced"),
        "strict_evidence": state.get("query_plan", {}).get("strict_evidence", False),
        "embedding_model": embedding_model_label,
        "chat_model": settings_obj.LOCAL_MODEL_NAME or settings_obj.CHAT_MODEL,
        "dense_weight": cfg.dense_weight if use_hybrid else 1.0,
        "sparse_weight": cfg.sparse_weight if use_hybrid else 0.0,
    }


def embedding_model_label(settings_obj: Any) -> str:
    name = settings_obj.EMBEDDING_MODEL_NAME.strip()
    if name:
        return name
    return Path(settings_obj.EMBEDDING_MODEL_PATH).name or settings_obj.EMBEDDING_MODEL_PATH


def mode_label(mode: str) -> str:
    if not mode:
        return "主检索"
    if mode == "disabled":
        return "关闭"
    if mode.startswith("hyde"):
        if "fallback" in mode:
            return "HyDE(回退)"
        return "HyDE"
    if mode.startswith("dense"):
        return "Dense"
    if mode.startswith("hybrid"):
        return "Hybrid"
    return mode
