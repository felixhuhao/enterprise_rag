"""Non-streaming query workflow entry point."""

from app.rag.query.build_prompt import build_prompt_node
from app.rag.query.config import QueryConfig, get_default_query_config
from app.rag.query.generate import generate_answer_node
from app.rag.query.groundedness import groundedness_check_node
from app.rag.query.search_pipeline import run_search_pipeline
from app.rag.query.validate_citations import validate_citations_node


def run_query_graph(query: str, query_config: QueryConfig | None = None, extra_configurable: dict | None = None) -> dict:
    """入口函数。extra_configurable 传入 allowed_document_ids 等 request-level 字段。"""
    cfg = query_config or get_default_query_config()
    configurable = {"query_config": cfg}
    if extra_configurable:
        configurable.update(extra_configurable)
    config = {"configurable": configurable}

    state = run_search_pipeline(query, config)
    state.update(build_prompt_node(state, config))
    state.update(generate_answer_node(state))
    state.update(validate_citations_node(state))
    state.update(groundedness_check_node(state, config))

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
        "groundedness": state.get("groundedness", {}),
    }
