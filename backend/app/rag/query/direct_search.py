"""Shared direct retrieval runner for search, HyDE, query expansion, and RRF."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from langgraph.graph.state import RunnableConfig

from app.rag.query.fallback import empty_fallback_info, merge_fallback_info
from app.rag.query.planner import get_query_plan
from app.rag.query.query_expansion import query_expansion_node
from app.rag.query.rrf_fusion import rrf_fusion_node
from app.rag.query.state import QueryState
from app.utils.time import tick_ms

logger = logging.getLogger(__name__)

SearchFn = Callable[[dict, RunnableConfig], dict]


def run_direct_search(
    state: QueryState,
    config: RunnableConfig,
    *,
    search_fn: SearchFn | None = None,
    hyde_fn: SearchFn | None = None,
) -> dict:
    """Run one direct retrieval pass and return fused search_results."""
    if search_fn is None:
        from app.rag.query.search import search_node
        search_fn = search_node
    if hyde_fn is None:
        from app.rag.query.hyde_search import hyde_search_node
        hyde_fn = hyde_search_node
    plan = get_query_plan(state, config)

    if plan.get("use_query_expansion"):
        updates = _run_query_expansion_search(state, config, search_fn)
    else:
        updates = _run_search_and_hyde(state, config, search_fn, hyde_fn, plan)

    fusion_state = {**state, **updates}
    t = time.monotonic()
    fused = rrf_fusion_node(fusion_state, config)
    return {**updates, **fused, "_rrf_fusion_ms": tick_ms(t)}


def _run_search_and_hyde(
    state: QueryState,
    config: RunnableConfig,
    search_fn: SearchFn,
    hyde_fn: SearchFn,
    plan: dict,
) -> dict:
    if plan.get("use_hyde"):
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_primary = pool.submit(search_fn, state, config)
            f_hyde = pool.submit(hyde_fn, state, config)
            primary = f_primary.result()
            hyde = f_hyde.result()
    else:
        primary = search_fn(state, config)
        hyde = _disabled_hyde()

    return {
        **primary,
        **hyde,
        "search_results_expanded": [],
        "search_modes_expanded": [],
        "expanded_queries": [],
        "per_query_counts": {"original": len(primary.get("search_results", []))},
        "query_expansion_trace": [],
        "fallback_info": _merge_infos(primary.get("fallback_info"), hyde.get("fallback_info")),
    }


def _run_query_expansion_search(
    state: QueryState,
    config: RunnableConfig,
    search_fn: SearchFn,
) -> dict:
    expansion = query_expansion_node(state, config)
    expanded_queries = expansion.get("expanded_queries", [])
    original_query = state.get("rewritten_query") or state["query"]

    if not expanded_queries:
        primary = search_fn(state, config)
        return {
            **primary,
            "search_results_hyde": [],
            "search_mode_hyde": "disabled",
            "search_results_expanded": [],
            "search_modes_expanded": [],
            "expanded_queries": [],
            "per_query_counts": {"original": len(primary.get("search_results", []))},
            "query_expansion_trace": [],
            "fallback_info": primary.get("fallback_info") or empty_fallback_info(),
        }

    with ThreadPoolExecutor(max_workers=min(1 + len(expanded_queries), 5)) as pool:
        f_primary = pool.submit(search_fn, state, config)
        expanded_futures = [
            pool.submit(_safe_expanded_search, search_fn, state, config, query, i)
            for i, query in enumerate(expanded_queries)
        ]
        primary = f_primary.result()
        expanded = [future.result() for future in expanded_futures]

    expanded_results = [item.get("search_results", []) for item in expanded]
    expanded_modes = [str(item.get("search_mode", "")) for item in expanded]
    counts = {"original": len(primary.get("search_results", []))}
    trace = [{"label": "original", "query": original_query, "count": counts["original"]}]
    for i, query in enumerate(expanded_queries):
        key = f"expanded_{i}"
        count = len(expanded_results[i]) if i < len(expanded_results) else 0
        counts[key] = count
        trace.append({"label": f"expanded_{i + 1}", "query": query, "count": count})

    return {
        **primary,
        "search_results_hyde": [],
        "search_mode_hyde": "disabled",
        "search_results_expanded": expanded_results,
        "search_modes_expanded": expanded_modes,
        "expanded_queries": expanded_queries,
        "per_query_counts": counts,
        "query_expansion_trace": trace,
        "fallback_info": _merge_infos(
            primary.get("fallback_info"),
            *(item.get("fallback_info") for item in expanded),
        ),
    }


def _safe_expanded_search(
    search_fn: SearchFn,
    state: QueryState,
    config: RunnableConfig,
    query: str,
    index: int,
) -> dict:
    variant = dict(state)
    variant["rewritten_query"] = query
    try:
        return search_fn(variant, config)
    except Exception:
        logger.warning("Expanded query search failed: index=%s query=%r", index, query, exc_info=True)
        return {
            "search_results": [],
            "search_mode": f"expanded_{index}_failed",
            "fallback_info": empty_fallback_info(),
        }


def _disabled_hyde() -> dict:
    return {
        "search_results_hyde": [],
        "search_mode_hyde": "disabled",
        "fallback_info": empty_fallback_info(),
    }


def _merge_infos(*infos: dict | None) -> dict:
    merged = empty_fallback_info()
    for info in infos:
        merged = merge_fallback_info(merged, info)
    return merged
