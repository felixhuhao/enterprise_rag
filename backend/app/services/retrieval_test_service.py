"""Retrieval-only test runner for knowledge-base debugging."""

from __future__ import annotations

import logging

from langgraph.graph.state import RunnableConfig

from app.config import settings
from app.rag.query.config import QueryConfig, get_default_query_config
from app.rag.query.search_pipeline import SearchPipelineHooks, SearchPipelineNodes, run_search_pipeline
from app.rag.query.state import QueryState
from app.services import retrieval_test_formatting
from app.services import retrieval_test_search

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
    table_paths: dict[str, list[str]] = {}
    hooks = SearchPipelineHooks(
        after_direct_search=lambda st: _localize_retrieval_paths(st.get("search_results", [])),
        after_multi_hop_search=lambda st: _apply_default_path(st.get("search_results", []), "Multi-hop"),
        before_table_expand=lambda st: _capture_table_paths(st, table_paths),
        after_table_expand=lambda st: _apply_table_paths(st.get("search_results", []), table_paths),
    )
    nodes = SearchPipelineNodes(
        entity_confirm=_entity_confirm_node,
        query_plan=_query_plan_node,
        rewrite_query=_rewrite_query_node,
        table_expand=_table_expand_node,
        rerank=lambda st, conf: _retrieval_test_rerank_node(st, conf, cfg),
        diversify_context=_diversify_context_node,
        context_expand=_context_expand_node,
        multi_hop_search=_run_multi_hop_search,
        should_run_multi_hop=_should_run_multi_hop,
    )
    state = run_search_pipeline(
        query,
        run_config,
        trace=trace,
        nodes=nodes,
        hooks=hooks,
        search_fn=lambda st, conf: _run_primary_search(st, conf, cfg, use_hybrid=use_hybrid),
        hyde_fn=_hyde_search_node,
        enable_post_rerank_fallback=False,
    )

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
        "alias_trace": state.get("alias_trace", []),
        "expanded_queries": state.get("expanded_queries", []),
        "per_query_counts": state.get("per_query_counts", {}),
        "query_expansion_trace": state.get("query_expansion_trace", []),
        "hop_plan": state.get("hop_plan", "direct"),
        "hop_trace": state.get("hop_trace", []),
        "retrieval_flavor": state.get("query_plan", {}).get("retrieval_flavor", "balanced"),
        "strict_evidence": state.get("query_plan", {}).get("strict_evidence", False),
        "query_plan": state.get("query_plan", {}),
        "routing_trace": state.get("routing_trace", {}),
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


def _run_primary_search(state: QueryState, run_config: RunnableConfig, cfg: QueryConfig, *, use_hybrid: bool) -> dict:
    return retrieval_test_search.run_primary_search(
        state,
        run_config,
        cfg,
        use_hybrid=use_hybrid,
        hybrid_search=_search_node,
        acl_filter=_retrieval_acl_filter,
        combine_acl=_combine_acl,
        embed_query=_embed_query,
        dense_search=_dense_only_search_limited,
    )


def _should_run_multi_hop(state: QueryState, query: str, plan: dict) -> bool:
    return bool(plan.get("use_multi_hop"))


def _run_multi_hop_search(
    state: QueryState,
    query: str,
    run_config: RunnableConfig,
    cfg: QueryConfig,
    trace: dict,
) -> dict:
    from app.rag.query.multi_hop import run_multi_hop_search

    return run_multi_hop_search(state, query, run_config, cfg, trace)


def _run_multi_entity_dense_search(state: QueryState, cfg: QueryConfig, acl_filter: str | None = None) -> dict:
    return retrieval_test_search.run_multi_entity_dense_search(
        state,
        cfg,
        acl_filter,
        combine_acl=_combine_acl,
        embed_query=_embed_query,
        dense_search=_dense_only_search_limited,
    )


def _apply_default_path(rows: list[dict], label: str):
    for row in rows:
        if row.get("retrieval_paths"):
            continue
        row["retrieval_paths"] = [label]
        row["retrieval_path"] = label


def _capture_table_paths(state: QueryState, table_paths: dict[str, list[str]]):
    table_paths.clear()
    table_paths.update(_table_path_map(state.get("search_results", [])))


def _localize_retrieval_paths(rows: list[dict]):
    for row in rows:
        paths = row.get("retrieval_paths") or []
        mapped = [_mode_label(str(path)) for path in paths if path]
        if mapped:
            row["retrieval_paths"] = mapped
            row["retrieval_path"] = " + ".join(mapped)


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


def _retrieval_test_rerank_node(state: QueryState, config: RunnableConfig, cfg: QueryConfig) -> dict:
    if cfg.use_rerank:
        return _rerank_node(state, config)
    results = state.get("search_results", [])[:cfg.rerank_max_top_k]
    return {
        "search_results": results,
        "rerank_candidates": list(results),
        "rerank_debug": [],
    }


def _format_result(row: dict, rank: int, *, use_rerank: bool) -> dict:
    return retrieval_test_formatting.format_result(row, rank, use_rerank=use_rerank)


def _strategy_summary(cfg: QueryConfig, use_hybrid: bool, state: QueryState) -> dict:
    return retrieval_test_formatting.strategy_summary(
        cfg,
        use_hybrid,
        state,
        settings_obj=settings,
        embedding_model_label=_embedding_model_label(),
    )


def _embedding_model_label() -> str:
    return retrieval_test_formatting.embedding_model_label(settings)


def _mode_label(mode: str) -> str:
    return retrieval_test_formatting.mode_label(mode)


def _entity_confirm_node(state: QueryState, config: RunnableConfig) -> dict:
    from app.rag.query.entity_confirm import entity_confirm_node

    return entity_confirm_node(state, config)


def _rewrite_query_node(state: QueryState, config: RunnableConfig) -> dict:
    from app.rag.query.rewrite_query import rewrite_query_node

    return rewrite_query_node(state, config)


def _query_plan_node(state: QueryState, config: RunnableConfig) -> dict:
    from app.rag.query.planner import query_plan_node

    return query_plan_node(state, config)


def _search_node(state: QueryState, config: RunnableConfig) -> dict:
    from app.rag.query.search import search_node

    return search_node(state, config)


def _hyde_search_node(state: QueryState, config: RunnableConfig) -> dict:
    from app.rag.query.hyde_search import hyde_search_node

    return hyde_search_node(state, config)


def _table_expand_node(state: QueryState, config: RunnableConfig) -> dict:
    from app.rag.query.table_expand import table_expand_node

    return table_expand_node(state, config)


def _rerank_node(state: QueryState, config: RunnableConfig) -> dict:
    from app.rag.query.rerank import rerank_node

    return rerank_node(state, config)


def _diversify_context_node(state: QueryState, config: RunnableConfig) -> dict:
    from app.rag.query.diversify_context import diversify_context_node

    return diversify_context_node(state, config)


def _context_expand_node(state: QueryState, config: RunnableConfig) -> dict:
    from app.rag.query.context_expand import context_expand_node

    return context_expand_node(state, config)


def _embed_query(query: str) -> list[float]:
    from app.rag.embeddings.dense_embedding import dense_embedding

    return dense_embedding.embed_query(query)


def _dense_only_search_limited(query_dense, entity_filter, limit: int) -> list[dict]:
    from app.rag.query.search import _dense_only_search_limited as dense_only_search_limited

    return dense_only_search_limited(query_dense, entity_filter, limit)
