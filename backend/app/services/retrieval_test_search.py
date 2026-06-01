"""Search helpers for the retrieval-test service."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app.rag.query.config import QueryConfig
from app.rag.query.fallback import empty_fallback_info, fallback_blocked, fallback_used

SearchNodeFn = Callable[[dict, dict], dict]
AclFilterFn = Callable[[dict], tuple[str | None, list[str] | None]]
CombineAclFn = Callable[[str | None, str | None], str | None]
EmbedQueryFn = Callable[[str], list[float]]
DenseSearchFn = Callable[[list[float], str | None, int], list[dict]]


def run_primary_search(
    state: dict,
    run_config: dict,
    cfg: QueryConfig,
    *,
    use_hybrid: bool,
    hybrid_search: SearchNodeFn,
    acl_filter: AclFilterFn,
    combine_acl: CombineAclFn,
    embed_query: EmbedQueryFn,
    dense_search: DenseSearchFn,
) -> dict:
    from app.rag.query.scoring_utils import need_fallback
    from app.rag.query.planner import plan_allows_entity_fallback, plan_budget

    acl_expr, allowed_ids = acl_filter(run_config)
    if allowed_ids is not None and not allowed_ids:
        return {"search_results": [], "search_mode": "acl_empty", "fallback_info": empty_fallback_info()}

    if use_hybrid:
        return hybrid_search(state, run_config)

    if state.get("entity_mode") == "multi_explicit":
        return run_multi_entity_dense_search(
            state,
            cfg,
            acl_expr,
            combine_acl=combine_acl,
            embed_query=embed_query,
            dense_search=dense_search,
        )

    query = state.get("rewritten_query") or state["query"]
    entity_filter = state.get("entity_filter") or None
    combined = combine_acl(entity_filter, acl_expr)
    query_dense = embed_query(query)
    budget = plan_budget(state, run_config)
    search_limit = int(budget.get("search_limit") or cfg.search_limit)

    results = dense_search(query_dense, combined, search_limit)
    should_fallback = bool(entity_filter) and need_fallback(results, combined, cfg)
    info = empty_fallback_info()
    if should_fallback:
        if plan_allows_entity_fallback(state, run_config):
            results = dense_search(query_dense, acl_expr, search_limit)
            mode = "dense_filtered_fallback_unfiltered"
            info = fallback_used(entity_filter)
        else:
            mode = "dense_filtered"
            info = fallback_blocked(entity_filter)
    else:
        mode = "dense_filtered" if combined else "dense"
    return {"search_results": results, "search_mode": mode, "fallback_info": info}


def run_multi_entity_dense_search(
    state: dict,
    cfg: QueryConfig,
    acl_filter: str | None = None,
    *,
    combine_acl: CombineAclFn,
    embed_query: EmbedQueryFn,
    dense_search: DenseSearchFn,
) -> dict:
    """Dense-only variant of multi-entity retrieval for the retrieval test page."""
    query = state.get("rewritten_query") or state["query"]
    matched = state.get("matched_entities", [])
    n = max(len(matched), 1)
    per_limit = max(cfg.search_limit // n, 5)
    query_dense = embed_query(query)

    def _search_one(entity: str) -> tuple[str, list[dict], str]:
        from app.rag.query.filter_utils import build_entity_expr
        combined = combine_acl(build_entity_expr(entity), acl_filter)
        try:
            rows = dense_search(query_dense, combined, per_limit)
            return entity, rows, "dense_filtered"
        except Exception:
            return entity, [], "failed"

    all_results: list[dict] = []
    per_counts: dict[str, int] = {}
    all_failed = True
    with ThreadPoolExecutor(max_workers=min(n, 4)) as pool:
        futures = [pool.submit(_search_one, entity) for entity in matched]
        for future in futures:
            entity, rows, mode = future.result()
            per_counts[entity] = len(rows)
            all_results.extend(rows)
            if mode != "failed":
                all_failed = False

    if all_failed:
        raise RuntimeError(f"多实体 dense 检索全部失败: entities={matched}")

    seen: dict[str, dict] = {}
    for row in all_results:
        key = str(row.get("chunk_key") or row.get("chunk_id") or f"{row.get('document_id')}|{row.get('source_type')}|{row.get('part')}")
        if key not in seen or row["score"] > seen[key]["score"]:
            seen[key] = row

    cap = min(len(seen), cfg.search_limit * 2)
    return {
        "search_results": sorted(seen.values(), key=lambda x: x["score"], reverse=True)[:cap],
        "search_mode": "multi_dense_filtered",
        "per_entity_counts": per_counts,
        "fallback_info": empty_fallback_info(),
    }
