"""Non-streaming query workflow entry point."""

import time

from app.rag.query.build_prompt import build_prompt_node
from app.rag.query.config import QueryConfig, get_default_query_config
from app.rag.query.generate import generate_answer_node
from app.rag.query.groundedness import groundedness_check_node
from app.rag.query.search_pipeline import run_search_pipeline
from app.rag.query.validate_citations import validate_citations_node
from app.utils.time import tick_ms


_OBSERVABILITY_STATE_KEYS = (
    "confirmed_entity",
    "entity_mode",
    "matched_entities",
    "per_entity_counts",
    "query_plan",
    "routing_trace",
    "fallback_info",
    "search_results",
    "rerank_candidates",
    "rerank_debug",
    "context_map",
    "search_mode",
    "search_mode_hyde",
    "search_modes_expanded",
    "citations",
)


def run_query_graph(query: str, query_config: QueryConfig | None = None, extra_configurable: dict | None = None) -> dict:
    """入口函数。extra_configurable 传入 allowed_document_ids 等 request-level 字段。"""
    t0 = time.monotonic()
    cfg = query_config or get_default_query_config()
    configurable = {"query_config": cfg}
    if extra_configurable:
        configurable.update(extra_configurable)
    config = {"configurable": configurable}

    trace: dict = {}
    state = run_search_pipeline(query, config, trace=trace)

    t = time.monotonic()
    state.update(build_prompt_node(state, config))
    trace["build_prompt_ms"] = tick_ms(t)
    trace["retrieval_wall_ms"] = trace.get("retrieval_wall_ms", 0) + trace["build_prompt_ms"]

    t = time.monotonic()
    state.update(generate_answer_node(state))
    trace["generate_ms"] = tick_ms(t)

    t = time.monotonic()
    state.update(validate_citations_node(state))
    trace["citation_validation_ms"] = tick_ms(t)

    t = time.monotonic()
    state.update(groundedness_check_node(state, config))
    trace["groundedness_ms"] = tick_ms(t)
    trace["total_ms"] = tick_ms(t0)
    state["trace"] = trace

    return {
        "answer": state.get("answer", ""),
        "citations": state.get("citations", []),
        "results_count": len(state.get("search_results", [])),
        "entity": state.get("confirmed_entity", ""),
        "rewritten_query": state.get("rewritten_query", ""),
        "entity_mode": state.get("entity_mode", "none"),
        "matched_entities": state.get("matched_entities", []),
        "per_entity_counts": state.get("per_entity_counts", {}),
        "expanded_queries": state.get("expanded_queries", []),
        "query_expansion_trace": state.get("query_expansion_trace", []),
        "retrieval_flavor": state.get("query_plan", {}).get("retrieval_flavor", "balanced"),
        "strict_evidence": state.get("query_plan", {}).get("strict_evidence", False),
        "query_plan": state.get("query_plan", {}),
        "fallback_info": state.get("fallback_info", {}),
        "search_mode": state.get("search_mode", ""),
        "search_mode_hyde": state.get("search_mode_hyde", ""),
        "groundedness": state.get("groundedness", {}),
        "_observability_state": {
            key: state.get(key)
            for key in _OBSERVABILITY_STATE_KEYS
            if key in state
        },
        "_observability_trace": trace,
        "_token_usage": state.get("token_usage", {}),
    }
