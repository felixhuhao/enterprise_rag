"""RRF (Reciprocal Rank Fusion) for merging retrieval result sets."""

from __future__ import annotations

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import get_query_config
from app.rag.query.planner import plan_budget
from app.rag.query.state import QueryState


def rrf_fusion_node(state: QueryState, config: RunnableConfig) -> dict:
    """Merge primary, HyDE, and expanded-query results with RRF."""
    cfg = get_query_config(config)
    budget = plan_budget(state, config)
    all_sets = _collect_result_sets(state)

    if not all_sets:
        return {"search_results": []}

    if len(all_sets) == 1:
        _, results, label = all_sets[0]
        return {"search_results": [_with_paths(doc, [label]) for doc in results]}

    k = cfg.rrf_k
    scores: dict[str, float] = {}
    doc_map: dict[str, dict] = {}
    path_map: dict[str, set[str]] = {}

    for _, results, label in all_sets:
        for rank, doc in enumerate(results):
            key = _dedup_key(doc)
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
            path_map.setdefault(key, set()).add(label)
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


def _collect_result_sets(state: QueryState) -> list[tuple[str, list[dict], str]]:
    sets: list[tuple[str, list[dict], str]] = []
    primary = state.get("search_results", [])
    if primary:
        sets.append(("primary", primary, _mode_label(state.get("search_mode", ""))))

    hyde = state.get("search_results_hyde", [])
    if hyde:
        sets.append(("hyde", hyde, _mode_label(state.get("search_mode_hyde", ""))))

    expanded_sets = state.get("search_results_expanded", []) or []
    expanded_modes = state.get("search_modes_expanded", []) or []
    for i, results in enumerate(expanded_sets):
        if not results:
            continue
        mode = expanded_modes[i] if i < len(expanded_modes) else ""
        sets.append((f"expanded_{i}", results, _expanded_label(i, mode)))
    return sets


def _expanded_label(index: int, mode: str) -> str:
    label = f"expanded_{index + 1}"
    if "fallback" in mode:
        return f"{label}_fallback"
    return label


def _dedup_key(doc: dict) -> str:
    """Prefer stable chunk_key, then Milvus chunk_id, then stable-ish metadata."""
    if doc.get("chunk_key"):
        return str(doc["chunk_key"])
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
