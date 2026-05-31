"""LangGraph query workflow.

START → entity_confirm → rewrite_query → [search, hyde_search] → rrf_fusion
→ table_expand → rerank → diversify_context → context_expand → build_prompt
→ generate_answer → validate_citations → END
"""

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.rag.query.build_prompt import build_prompt_node
from app.rag.query.config import QueryConfig, get_default_query_config
from app.rag.query.context_expand import context_expand_node
from app.rag.query.diversify_context import diversify_context_node
from app.rag.query.direct_search import run_direct_search
from app.rag.query.entity_confirm import entity_confirm_node
from app.rag.query.fallback import (
    REASON_LOW_SCORE_OR_INSUFFICIENT_HITS,
    fallback_blocked,
    fallback_used,
    merge_fallback_info,
    state_fallback_info,
)
from app.rag.query.generate import generate_answer_node
from app.rag.query.groundedness import groundedness_check_node
from app.rag.query.hyde_search import hyde_search_node
from app.rag.query.planner import get_query_plan, plan_allows_entity_fallback, query_plan_node
from app.rag.query.rerank import rerank_node
from app.rag.query.rewrite_query import rewrite_query_node
from app.rag.query.rrf_fusion import rrf_fusion_node
from app.rag.query.search import search_node
from app.rag.query.state import QueryState
from app.rag.query.table_expand import table_expand_node
from app.rag.query.validate_citations import validate_citations_node

_builder = StateGraph(QueryState)

_builder.add_node("entity_confirm", entity_confirm_node)
_builder.add_node("query_plan", query_plan_node)
_builder.add_node("rewrite_query", rewrite_query_node)
_builder.add_node("search", search_node)
_builder.add_node("hyde_search", hyde_search_node)
_builder.add_node("rrf_fusion", rrf_fusion_node)
_builder.add_node("table_expand", table_expand_node)
_builder.add_node("rerank", rerank_node)
_builder.add_node("diversify_context", diversify_context_node)
_builder.add_node("context_expand", context_expand_node)
_builder.add_node("build_prompt", build_prompt_node)
_builder.add_node("generate_answer", generate_answer_node)
_builder.add_node("validate_citations", validate_citations_node)
_builder.add_node("groundedness_check", groundedness_check_node)

_builder.add_edge(START, "entity_confirm")
_builder.add_edge("entity_confirm", "query_plan")
_builder.add_edge("query_plan", "rewrite_query")
# fan-out: rewrite_query → search + hyde_search 并行
_builder.add_edge("rewrite_query", "search")
_builder.add_edge("rewrite_query", "hyde_search")
# fan-in: 两路汇聚到 rrf_fusion
_builder.add_edge("search", "rrf_fusion")
_builder.add_edge("hyde_search", "rrf_fusion")
_builder.add_edge("rrf_fusion", "table_expand")
_builder.add_edge("table_expand", "rerank")
_builder.add_edge("rerank", "diversify_context")
_builder.add_edge("diversify_context", "context_expand")
_builder.add_edge("context_expand", "build_prompt")
_builder.add_edge("build_prompt", "generate_answer")
_builder.add_edge("generate_answer", "validate_citations")
_builder.add_edge("validate_citations", "groundedness_check")
_builder.add_edge("groundedness_check", END)

query_graph = _builder.compile()


def run_query_graph(query: str, query_config: QueryConfig | None = None, extra_configurable: dict | None = None) -> dict:
    """入口函数。extra_configurable 传入 allowed_document_ids 等 request-level 字段。"""
    from app.rag.query.multi_hop import _decide_multi_hop, run_multi_hop_search

    cfg = query_config or get_default_query_config()
    configurable = {"query_config": cfg}
    if extra_configurable:
        configurable.update(extra_configurable)
    config = {"configurable": configurable}

    state: dict = {"query": query}
    trace: dict = {}
    state.update(entity_confirm_node(state, config))
    state.update(query_plan_node(state, config))
    plan = get_query_plan(state, config)

    if plan.get("use_multi_hop") and _decide_multi_hop(state.get("entity_mode", "none"), query):
        state.update(run_multi_hop_search(state, query, config, cfg, trace))
        state.update(table_expand_node(state, config))
        state.update(rerank_node(state, config))
    else:
        state.update(rewrite_query_node(state, config))
        state.update(run_direct_search(state, config))
        state.update(table_expand_node(state, config))
        state.update(rerank_node(state, config))

        entity_filter = state.get("entity_filter")
        already_fell_back = (
            state_fallback_info(state).get("used")
            or "fallback" in state.get("search_mode", "")
            or "fallback" in state.get("search_mode_hyde", "")
            or any("fallback" in mode for mode in state.get("search_modes_expanded", []))
        )
        results = state.get("search_results", [])
        if entity_filter and not already_fell_back and results:
            top_score = results[0].get("score", 0)
            if top_score < cfg.entity_filter_rerank_min_score and plan_allows_entity_fallback(state, config):
                state["entity_filter"] = ""
                state.update(run_direct_search(state, config))
                state.update(table_expand_node(state, config))
                state.update(rerank_node(state, config))
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

    state.update(diversify_context_node(state, config))
    state.update(context_expand_node(state, config))
    state.update(build_prompt_node(state, config))
    state.update(generate_answer_node(state))
    state.update(validate_citations_node(state))
    state.update(groundedness_check_node(state, config))
    result = state
    return {
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "results_count": len(result.get("search_results", [])),
        "entity": result.get("confirmed_entity", ""),
        "rewritten_query": result.get("rewritten_query", ""),
        "entity_mode": result.get("entity_mode", "none"),
        "matched_entities": result.get("matched_entities", []),
        "per_entity_counts": result.get("per_entity_counts", {}),
        "expanded_queries": result.get("expanded_queries", []),
        "query_expansion_trace": result.get("query_expansion_trace", []),
        "retrieval_flavor": result.get("query_plan", {}).get("retrieval_flavor", "balanced"),
        "strict_evidence": result.get("query_plan", {}).get("strict_evidence", False),
        "query_plan": result.get("query_plan", {}),
        "fallback_info": result.get("fallback_info", {}),
        "groundedness": result.get("groundedness", {}),
    }
