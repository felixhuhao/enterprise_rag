"""Shared retrieval pipeline runner used by streaming chat and retrieval tests."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import QueryConfig, get_query_config
from app.rag.query.fallback import (
    REASON_LOW_SCORE_OR_INSUFFICIENT_HITS,
    fallback_blocked,
    fallback_used,
    merge_fallback_info,
    state_fallback_info,
)
from app.rag.query.planner import get_query_plan, plan_allows_entity_fallback
from app.utils.time import tick_ms

logger = logging.getLogger(__name__)

NodeFn = Callable[[dict, RunnableConfig], dict]
SearchFn = Callable[[dict, RunnableConfig], dict]
StateHook = Callable[[dict], None]
MultiHopFn = Callable[[dict, str, RunnableConfig, QueryConfig, dict], dict]
ShouldRunMultiHopFn = Callable[[dict, str, dict], bool]


def _entity_confirm_node(state: dict, config: RunnableConfig) -> dict:
    from app.rag.query.entity_confirm import entity_confirm_node

    return entity_confirm_node(state, config)


def _query_plan_node(state: dict, config: RunnableConfig) -> dict:
    from app.rag.query.planner import query_plan_node

    return query_plan_node(state, config)


def _rewrite_query_node(state: dict, config: RunnableConfig) -> dict:
    from app.rag.query.rewrite_query import rewrite_query_node

    return rewrite_query_node(state, config)


def _table_expand_node(state: dict, config: RunnableConfig) -> dict:
    from app.rag.query.table_expand import table_expand_node

    return table_expand_node(state, config)


def _rerank_node(state: dict, config: RunnableConfig) -> dict:
    from app.rag.query.rerank import rerank_node

    return rerank_node(state, config)


def _diversify_context_node(state: dict, config: RunnableConfig) -> dict:
    from app.rag.query.diversify_context import diversify_context_node

    return diversify_context_node(state, config)


def _context_expand_node(state: dict, config: RunnableConfig) -> dict:
    from app.rag.query.context_expand import context_expand_node

    return context_expand_node(state, config)


def _run_multi_hop_search(
    state: dict,
    query: str,
    run_config: RunnableConfig,
    cfg: QueryConfig,
    trace: dict,
) -> dict:
    from app.rag.query.multi_hop import run_multi_hop_search

    return run_multi_hop_search(state, query, run_config, cfg, trace)


def _should_run_multi_hop(state: dict, query: str, plan: dict) -> bool:
    from app.rag.query.multi_hop import _decide_multi_hop

    return bool(plan.get("use_multi_hop") and _decide_multi_hop(state.get("entity_mode", "none"), query))


@dataclass
class SearchPipelineNodes:
    entity_confirm: NodeFn = _entity_confirm_node
    query_plan: NodeFn = _query_plan_node
    rewrite_query: NodeFn = _rewrite_query_node
    table_expand: NodeFn = _table_expand_node
    rerank: NodeFn = _rerank_node
    diversify_context: NodeFn = _diversify_context_node
    context_expand: NodeFn = _context_expand_node
    multi_hop_search: MultiHopFn = _run_multi_hop_search
    should_run_multi_hop: ShouldRunMultiHopFn = _should_run_multi_hop


@dataclass
class SearchPipelineHooks:
    after_direct_search: StateHook | None = None
    after_multi_hop_search: StateHook | None = None
    before_table_expand: StateHook | None = None
    after_table_expand: StateHook | None = None


def run_search_pipeline(
    query: str,
    run_config: RunnableConfig,
    *,
    trace: dict | None = None,
    initial_state: dict | None = None,
    nodes: SearchPipelineNodes | None = None,
    hooks: SearchPipelineHooks | None = None,
    search_fn: SearchFn | None = None,
    hyde_fn: SearchFn | None = None,
    enable_post_rerank_fallback: bool = True,
) -> dict:
    """Run retrieval through context expansion and return the final state.

    Prompt construction and answer generation intentionally stay outside this
    runner so SSE orchestration can own streaming and persistence.
    """
    cfg = get_query_config(run_config)
    trace = trace if trace is not None else {}
    nodes = nodes or SearchPipelineNodes()
    hooks = hooks or SearchPipelineHooks()
    t0 = time.monotonic()
    state = dict(initial_state or {})
    state.setdefault("query", query)

    t = time.monotonic()
    state.update(nodes.entity_confirm(state, run_config))
    trace["entity_confirm_ms"] = tick_ms(t)

    t = time.monotonic()
    state.update(nodes.query_plan(state, run_config))
    trace["query_plan_ms"] = tick_ms(t)

    plan = get_query_plan(state, run_config)
    if nodes.should_run_multi_hop(state, query, plan):
        state["rewritten_query"] = query
        state.update(nodes.multi_hop_search(state, query, run_config, cfg, trace))
        if hooks.after_multi_hop_search:
            hooks.after_multi_hop_search(state)
        _run_table_expand_and_rerank(state, run_config, trace, nodes, hooks)
    else:
        _run_direct_with_fallback(
            state,
            run_config,
            cfg,
            trace,
            nodes,
            hooks,
            search_fn=search_fn,
            hyde_fn=hyde_fn,
            enable_post_rerank_fallback=enable_post_rerank_fallback,
        )

    t = time.monotonic()
    state.update(nodes.diversify_context(state, run_config))
    trace["diversify_context_ms"] = tick_ms(t)

    t = time.monotonic()
    state.update(nodes.context_expand(state, run_config))
    trace["context_expand_ms"] = tick_ms(t)

    trace["retrieval_wall_ms"] = tick_ms(t0)
    state["trace"] = trace
    return state


def _run_direct_with_fallback(
    state: dict,
    run_config: RunnableConfig,
    cfg: QueryConfig,
    trace: dict,
    nodes: SearchPipelineNodes,
    hooks: SearchPipelineHooks,
    *,
    search_fn: SearchFn | None,
    hyde_fn: SearchFn | None,
    enable_post_rerank_fallback: bool,
) -> None:
    _run_direct_retrieval(state, run_config, trace, nodes, hooks, search_fn=search_fn, hyde_fn=hyde_fn)
    _run_table_expand_and_rerank(state, run_config, trace, nodes, hooks)

    if not enable_post_rerank_fallback:
        return

    entity_filter = state.get("entity_filter")
    already_fell_back = (
        state_fallback_info(state).get("used")
        or "fallback" in state.get("search_mode", "")
        or "fallback" in state.get("search_mode_hyde", "")
        or any("fallback" in mode for mode in state.get("search_modes_expanded", []))
    )
    results = state.get("search_results", [])
    if not entity_filter or already_fell_back or not results:
        return

    top_score = results[0].get("score", 0)
    if top_score < cfg.entity_filter_rerank_min_score and plan_allows_entity_fallback(state, run_config):
        logger.info(
            "Post-rerank fallback: top_score=%.3f < %.3f, retrying unfiltered",
            top_score,
            cfg.entity_filter_rerank_min_score,
        )
        t_fb = time.monotonic()
        state["entity_filter"] = ""
        _run_direct_retrieval(state, run_config, trace, nodes, hooks, search_fn=search_fn, hyde_fn=hyde_fn)

        _run_table_expand_and_rerank(state, run_config, trace, nodes, hooks, record_trace=False)
        trace["post_rerank_fallback_ms"] = tick_ms(t_fb)

        state["search_mode"] = state.get("search_mode", "") + "_post_rerank_fallback"
        state["fallback_info"] = merge_fallback_info(
            state_fallback_info(state),
            fallback_used(entity_filter, REASON_LOW_SCORE_OR_INSUFFICIENT_HITS),
        )
    elif top_score < cfg.entity_filter_rerank_min_score:
        state["fallback_info"] = merge_fallback_info(
            state_fallback_info(state),
            fallback_blocked(entity_filter),
        )


def _run_direct_retrieval(
    state: dict,
    run_config: RunnableConfig,
    trace: dict,
    nodes: SearchPipelineNodes,
    hooks: SearchPipelineHooks,
    *,
    search_fn: SearchFn | None,
    hyde_fn: SearchFn | None,
) -> None:
    from app.rag.query.direct_search import run_direct_search

    t = time.monotonic()
    state.update(nodes.rewrite_query(state, run_config))
    trace["rewrite_ms"] = tick_ms(t)

    t = time.monotonic()
    kwargs = {}
    if search_fn is not None:
        kwargs["search_fn"] = search_fn
    if hyde_fn is not None:
        kwargs["hyde_fn"] = hyde_fn
    direct = run_direct_search(state, run_config, **kwargs)
    trace["search_hyde_ms"] = tick_ms(t)
    trace["rrf_fusion_ms"] = direct.pop("_rrf_fusion_ms", 0)
    state.update(direct)
    if hooks.after_direct_search:
        hooks.after_direct_search(state)


def _run_table_expand_and_rerank(
    state: dict,
    run_config: RunnableConfig,
    trace: dict,
    nodes: SearchPipelineNodes,
    hooks: SearchPipelineHooks,
    *,
    record_trace: bool = True,
) -> None:
    if hooks.before_table_expand:
        hooks.before_table_expand(state)

    t = time.monotonic()
    state.update(nodes.table_expand(state, run_config))
    if hooks.after_table_expand:
        hooks.after_table_expand(state)
    if record_trace:
        trace["table_expand_ms"] = tick_ms(t)

    t = time.monotonic()
    state.update(nodes.rerank(state, run_config))
    if record_trace:
        trace["rerank_ms"] = tick_ms(t)
