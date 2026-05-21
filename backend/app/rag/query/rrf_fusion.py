"""RRF (Reciprocal Rank Fusion) for merging search + HyDE results."""

from __future__ import annotations

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import get_query_config
from app.rag.query.state import QueryState


def rrf_fusion_node(state: QueryState, config: RunnableConfig) -> dict:
    """两路搜索结果 RRF 合并。HyDE 为空时退化为直接使用主搜索。"""
    cfg = get_query_config(config)
    results_a = state.get("search_results", [])
    results_b = state.get("search_results_hyde", [])

    if not results_b:
        return {"search_results": results_a}

    k = cfg.rrf_k
    scores: dict[str, float] = {}
    doc_map: dict[str, dict] = {}

    for rank, doc in enumerate(results_a):
        key = _dedup_key(doc)
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        if key not in doc_map:
            doc_map[key] = doc

    for rank, doc in enumerate(results_b):
        key = _dedup_key(doc)
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        if key not in doc_map:
            doc_map[key] = doc

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    fused = []
    for key, score in ranked[:cfg.rrf_max_results]:
        doc = doc_map[key].copy()
        doc["score"] = score
        fused.append(doc)

    return {"search_results": fused}


def _dedup_key(doc: dict) -> str:
    """优先用 chunk_id，fallback 到 document_id|source_type|table_id|part。"""
    if doc.get("chunk_id") is not None:
        return str(doc["chunk_id"])
    return f"{doc.get('document_id', '')}|{doc.get('source_type', '')}|{doc.get('table_id', '')}|{doc.get('part', '')}"
