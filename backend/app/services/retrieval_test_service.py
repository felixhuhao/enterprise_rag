"""Retrieval-only test runner for knowledge-base debugging."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app.config import settings
from app.rag.query.fallback import empty_fallback_info, fallback_blocked, fallback_used, merge_fallback_info
from app.rag.query.config import QueryConfig, get_default_query_config

logger = logging.getLogger(__name__)


def run_retrieval_test(
    query: str,
    *,
    top_k: int = 10,
    use_hybrid: bool = True,
    use_hyde: bool = True,
    use_rerank: bool = True,
    retrieval_flavor: str = "balanced",
    strict_evidence: bool = False,
    allowed_document_ids: list[str] | None = None,
) -> dict:
    """Run the query pipeline up to rerank, without prompt building or generation."""
    from app.rag.query.rrf_fusion import _dedup_key, rrf_fusion_node

    cfg = _build_config(
        top_k=top_k,
        use_hyde=use_hyde,
        use_rerank=use_rerank,
        retrieval_flavor=retrieval_flavor,
        strict_evidence=strict_evidence,
    )
    run_config = {"configurable": {
        "query_config": cfg,
        "allowed_document_ids": allowed_document_ids,
    }}
    trace: dict[str, int] = {}
    t0 = time.monotonic()
    state: dict = {"query": query}

    t = time.monotonic()
    state.update(_entity_confirm_node(state, run_config))
    trace["entity_confirm_ms"] = _tick_ms(t)

    t = time.monotonic()
    state.update(_query_plan_node(state, run_config))
    trace["query_plan_ms"] = _tick_ms(t)
    plan = state.get("query_plan", {})

    if _should_run_multi_hop(state, query, plan):
        state["rewritten_query"] = query
        state.update(_run_multi_hop_search(state, query, run_config, cfg, trace))
        _apply_default_path(state.get("search_results", []), "Multi-hop")
    else:
        t = time.monotonic()
        state.update(_rewrite_query_node(state, run_config))
        trace["rewrite_ms"] = _tick_ms(t)

        t = time.monotonic()
        primary = _run_primary_search(state, run_config, cfg, use_hybrid=use_hybrid)
        hyde = _hyde_search_node(state, run_config) if plan.get("use_hyde") else {
            "search_results_hyde": [],
            "search_mode_hyde": "disabled",
            "fallback_info": empty_fallback_info(),
        }
        fallback_info = merge_fallback_info(
            primary.get("fallback_info"),
            hyde.get("fallback_info"),
        )
        state.update(primary)
        state.update(hyde)
        state["fallback_info"] = fallback_info
        trace["search_hyde_ms"] = _tick_ms(t)

        path_map = _build_path_map(
            _dedup_key,
            state.get("search_results", []),
            state.get("search_mode", ""),
            state.get("search_results_hyde", []),
            state.get("search_mode_hyde", ""),
        )

        t = time.monotonic()
        state.update(rrf_fusion_node(state, run_config))
        _apply_paths(_dedup_key, state.get("search_results", []), path_map)
        trace["rrf_fusion_ms"] = _tick_ms(t)

    table_paths = _table_path_map(state.get("search_results", []))
    t = time.monotonic()
    state.update(_table_expand_node(state, run_config))
    _apply_table_paths(state.get("search_results", []), table_paths)
    trace["table_expand_ms"] = _tick_ms(t)

    t = time.monotonic()
    if use_rerank:
        state.update(_rerank_node(state, run_config))
    else:
        state["search_results"] = state.get("search_results", [])[:cfg.rerank_max_top_k]
        state["rerank_debug"] = []
    trace["rerank_ms"] = _tick_ms(t)

    t = time.monotonic()
    state.update(_context_expand_node(state, run_config))
    trace["context_expand_ms"] = _tick_ms(t)

    trace["retrieval_wall_ms"] = _tick_ms(t0)

    results = [
        _format_result(row, rank, use_rerank=use_rerank)
        for rank, row in enumerate(state.get("search_results", [])[:cfg.rerank_max_top_k], start=1)
    ]

    return {
        "query": query,
        "rewritten_query": state.get("rewritten_query", query),
        "confirmed_entity": state.get("confirmed_entity", ""),
        "entity_filter": state.get("entity_filter", ""),
        "entity_mode": state.get("entity_mode", "none"),
        "matched_entities": state.get("matched_entities", []),
        "per_entity_counts": state.get("per_entity_counts", {}),
        "hop_plan": state.get("hop_plan", "direct"),
        "hop_trace": state.get("hop_trace", []),
        "retrieval_flavor": state.get("query_plan", {}).get("retrieval_flavor", "balanced"),
        "strict_evidence": state.get("query_plan", {}).get("strict_evidence", False),
        "query_plan": state.get("query_plan", {}),
        "fallback_info": state.get("fallback_info", {}),
        "result_count": len(results),
        "trace": trace,
        "strategy": _strategy_summary(cfg, use_hybrid, state),
        "results": results,
    }


def _build_config(
    *,
    top_k: int,
    use_hyde: bool,
    use_rerank: bool,
    retrieval_flavor: str = "balanced",
    strict_evidence: bool = False,
) -> QueryConfig:
    cfg = get_default_query_config()
    cfg.search_limit = top_k
    cfg.hyde_limit = top_k
    cfg.rrf_max_results = max(top_k * 2, top_k)
    cfg.rerank_max_top_k = top_k
    cfg.rerank_min_top_k = min(cfg.rerank_min_top_k, top_k)
    cfg.use_hyde = use_hyde
    cfg.use_rerank = use_rerank
    cfg.retrieval_flavor = retrieval_flavor
    cfg.strict_evidence = strict_evidence
    cfg.clamp()
    return cfg


def _retrieval_acl_filter(run_config: dict) -> tuple[str | None, list[str] | None]:
    """Build ACL expr from retrieval test run_config.
    Returns (acl_expr, allowed_ids) where allowed_ids=None means no restriction,
    acl_expr=None with allowed_ids=[] means no access.
    """
    from app.rag.query.filter_utils import build_acl_expr, get_allowed_ids
    allowed = get_allowed_ids(run_config)
    if allowed is not None and not allowed:
        return None, []  # no access
    acl = build_acl_expr(allowed) if allowed else None
    return acl, allowed


def _combine_acl(entity_filter: str | None, acl_filter: str | None) -> str | None:
    """Combine entity and ACL filter."""
    from app.rag.query.filter_utils import combine_filters
    if acl_filter is None and entity_filter is None:
        return None
    return combine_filters(entity_filter, acl_filter)


def _run_primary_search(state: dict, run_config: dict, cfg: QueryConfig, *, use_hybrid: bool) -> dict:
    from app.rag.query.scoring_utils import need_fallback
    from app.rag.query.planner import plan_allows_entity_fallback, plan_budget

    acl_filter, allowed_ids = _retrieval_acl_filter(run_config)
    if allowed_ids is not None and not allowed_ids:
        return {"search_results": [], "search_mode": "acl_empty", "fallback_info": empty_fallback_info()}

    if use_hybrid:
        return _search_node(state, run_config)

    if state.get("entity_mode") == "multi_explicit":
        return _run_multi_entity_dense_search(state, cfg, acl_filter)

    query = state.get("rewritten_query") or state["query"]
    entity_filter = state.get("entity_filter") or None
    combined = _combine_acl(entity_filter, acl_filter)
    query_dense = _embed_query(query)
    budget = plan_budget(state, run_config)
    search_limit = int(budget.get("search_limit") or cfg.search_limit)

    results = _dense_only_search_limited(query_dense, combined, search_limit)
    should_fallback = bool(entity_filter) and need_fallback(results, combined, cfg)
    info = empty_fallback_info()
    if should_fallback:
        if plan_allows_entity_fallback(state, run_config):
            results = _dense_only_search_limited(query_dense, acl_filter, search_limit)
            mode = "dense_filtered_fallback_unfiltered"
            info = fallback_used(entity_filter)
        else:
            mode = "dense_filtered"
            info = fallback_blocked(entity_filter)
    else:
        mode = "dense_filtered" if combined else "dense"
    return {"search_results": results, "search_mode": mode, "fallback_info": info}


def _should_run_multi_hop(state: dict, query: str, plan: dict) -> bool:
    from app.rag.query.multi_hop import _decide_multi_hop

    return bool(plan.get("use_multi_hop") and _decide_multi_hop(state.get("entity_mode", "none"), query))


def _run_multi_hop_search(state: dict, query: str, run_config: dict, cfg: QueryConfig, trace: dict) -> dict:
    from app.rag.query.multi_hop import run_multi_hop_search

    return run_multi_hop_search(state, query, run_config, cfg, trace)


def _run_multi_entity_dense_search(state: dict, cfg: QueryConfig, acl_filter: str | None = None) -> dict:
    """Dense-only variant of multi-entity retrieval for the retrieval test page."""
    from concurrent.futures import ThreadPoolExecutor

    query = state.get("rewritten_query") or state["query"]
    matched = state.get("matched_entities", [])
    n = max(len(matched), 1)
    per_limit = max(cfg.search_limit // n, 5)
    query_dense = _embed_query(query)

    def _search_one(entity: str) -> tuple[str, list[dict], str]:
        from app.rag.query.filter_utils import build_entity_expr
        combined = _combine_acl(build_entity_expr(entity), acl_filter)
        try:
            rows = _dense_only_search_limited(query_dense, combined, per_limit)
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


def _build_path_map(
    dedup_key, primary: list[dict], primary_mode: str,
    hyde: list[dict], hyde_mode: str,
) -> dict[str, set[str]]:
    path_map: dict[str, set[str]] = {}
    for row in primary:
        path_map.setdefault(dedup_key(row), set()).add(_mode_label(primary_mode))
    for row in hyde:
        path_map.setdefault(dedup_key(row), set()).add(_mode_label(hyde_mode))
    return path_map


def _apply_paths(dedup_key, rows: list[dict], path_map: dict[str, set[str]]):
    for row in rows:
        paths = sorted(path_map.get(dedup_key(row), set()))
        row["retrieval_paths"] = paths
        row["retrieval_path"] = " + ".join(paths) if paths else "未知"


def _apply_default_path(rows: list[dict], label: str):
    for row in rows:
        if row.get("retrieval_paths"):
            continue
        row["retrieval_paths"] = [label]
        row["retrieval_path"] = label


def _table_path_map(rows: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in rows:
        table_id = row.get("table_id")
        if row.get("source_type") == "table_summary" and table_id:
            out[table_id] = row.get("retrieval_paths") or [row.get("retrieval_path", "主检索")]
    return out


def _apply_table_paths(rows: list[dict], table_paths: dict[str, list[str]]):
    for row in rows:
        table_id = row.get("table_id")
        if row.get("retrieval_paths"):
            continue
        if table_id and table_id in table_paths:
            paths = [*table_paths[table_id], "表格展开"]
            row["retrieval_paths"] = paths
            row["retrieval_path"] = " + ".join(paths)


def _format_result(row: dict, rank: int, *, use_rerank: bool) -> dict:
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


def _strategy_summary(cfg: QueryConfig, use_hybrid: bool, state: dict) -> dict:
    search_mode = state.get("search_mode", "")
    hyde_mode = state.get("search_mode_hyde", "")
    return {
        "top_k": cfg.rerank_max_top_k,
        "hybrid": use_hybrid,
        "hyde": bool(state.get("query_plan", {}).get("use_hyde", cfg.use_hyde)),
        "rerank": cfg.use_rerank,
        "table_expand": cfg.use_table_expand,
        "fallback": "fallback" in search_mode or "fallback" in hyde_mode,
        "search_mode": search_mode,
        "search_mode_hyde": hyde_mode,
        "retrieval_flavor": state.get("query_plan", {}).get("retrieval_flavor", "balanced"),
        "strict_evidence": state.get("query_plan", {}).get("strict_evidence", False),
        "embedding_model": _embedding_model_label(),
        "chat_model": settings.LOCAL_MODEL_NAME or settings.CHAT_MODEL,
        "dense_weight": cfg.dense_weight if use_hybrid else 1.0,
        "sparse_weight": cfg.sparse_weight if use_hybrid else 0.0,
    }


def _embedding_model_label() -> str:
    name = settings.EMBEDDING_MODEL_NAME.strip()
    if name:
        return name
    return Path(settings.EMBEDDING_MODEL_PATH).name or settings.EMBEDDING_MODEL_PATH


def _mode_label(mode: str) -> str:
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


def _tick_ms(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)


def _entity_confirm_node(state: dict, config: dict) -> dict:
    from app.rag.query.entity_confirm import entity_confirm_node

    return entity_confirm_node(state, config)


def _rewrite_query_node(state: dict, config: dict) -> dict:
    from app.rag.query.rewrite_query import rewrite_query_node

    return rewrite_query_node(state, config)


def _query_plan_node(state: dict, config: dict) -> dict:
    from app.rag.query.planner import query_plan_node

    return query_plan_node(state, config)


def _search_node(state: dict, config: dict) -> dict:
    from app.rag.query.search import search_node

    return search_node(state, config)


def _hyde_search_node(state: dict, config: dict) -> dict:
    from app.rag.query.hyde_search import hyde_search_node

    return hyde_search_node(state, config)


def _table_expand_node(state: dict, config: dict) -> dict:
    from app.rag.query.table_expand import table_expand_node

    return table_expand_node(state, config)


def _rerank_node(state: dict, config: dict) -> dict:
    from app.rag.query.rerank import rerank_node

    return rerank_node(state, config)


def _context_expand_node(state: dict, config: dict) -> dict:
    from app.rag.query.context_expand import context_expand_node

    return context_expand_node(state, config)


def _embed_query(query: str) -> list[float]:
    from app.rag.embeddings.dense_embedding import dense_embedding

    return dense_embedding.embed_query(query)


def _dense_only_search_limited(query_dense, entity_filter, limit: int) -> list[dict]:
    from app.rag.query.search import _dense_only_search_limited as dense_only_search_limited

    return dense_only_search_limited(query_dense, entity_filter, limit)
