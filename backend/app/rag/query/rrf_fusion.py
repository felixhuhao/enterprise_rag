"""RRF (Reciprocal Rank Fusion) for merging search + HyDE results."""

from __future__ import annotations

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import get_query_config
from app.rag.query.planner import plan_budget
from app.rag.query.state import QueryState


def rrf_fusion_node(state: QueryState, config: RunnableConfig) -> dict:
    """Merge primary search and HyDE results with RRF."""
    cfg = get_query_config(config)
    budget = plan_budget(state, config)
    results_a = state.get("search_results", [])
    results_b = state.get("search_results_hyde", [])
    mode_a = _mode_label(state.get("search_mode", ""))
    mode_b = _mode_label(state.get("search_mode_hyde", ""))

    if not results_b:
        return {"search_results": [_with_paths(doc, [mode_a]) for doc in results_a]}

    k = cfg.rrf_k
    scores: dict[str, float] = {}
    doc_map: dict[str, dict] = {}
    path_map: dict[str, set[str]] = {}

    for rank, doc in enumerate(results_a):
        key = _dedup_key(doc)
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        path_map.setdefault(key, set()).add(mode_a)
        if key not in doc_map:
            doc_map[key] = doc

    for rank, doc in enumerate(results_b):
        key = _dedup_key(doc)
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        path_map.setdefault(key, set()).add(mode_b)
        if key not in doc_map:
            doc_map[key] = doc

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    fused = []
    limit = int(budget.get("rrf_top_k") or cfg.rrf_max_results)
    for key, score in ranked[:limit]:
        doc = doc_map[key].copy()
        doc["score"] = score
        fused.append(_with_paths(doc, sorted(path_map.get(key, set()))))

    return {"search_results": fused}


def _dedup_key(doc: dict) -> str:
    """Prefer chunk_id, then fall back to stable metadata."""
    if doc.get("chunk_id") is not None:
        return str(doc["chunk_id"])
    return f"{doc.get('document_id', '')}|{doc.get('source_type', '')}|{doc.get('table_id', '')}|{doc.get('part', '')}"


def _with_paths(doc: dict, paths: list[str]) -> dict:
    row = doc.copy()
    existing = row.get("retrieval_paths") or []
    merged = [p for p in [*existing, *paths] if p]
    deduped = list(dict.fromkeys(merged))
    row["retrieval_paths"] = deduped
    row["retrieval_path"] = " + ".join(deduped) if deduped else "primary"
    return row


def _mode_label(mode: str) -> str:
    if not mode:
        return "primary"
    if mode == "disabled":
        return "disabled"
    if mode.startswith("hyde"):
        return "hyde_fallback" if "fallback" in mode else "hyde"
    if mode.startswith("dense"):
        return "dense"
    if mode.startswith("hybrid"):
        return "hybrid_fallback" if "fallback" in mode else "hybrid"
    return mode
