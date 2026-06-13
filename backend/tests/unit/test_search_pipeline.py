"""Unit tests for the shared retrieval pipeline runner."""

from app.rag.query.config import QueryConfig
from app.rag.query.search_pipeline import SearchPipelineNodes, run_search_pipeline


def _config() -> dict:
    return {"configurable": {"query_config": QueryConfig(use_hyde=False, use_rerank=False)}}


def _plan(*, fallback_allowed: bool = True) -> dict:
    return {
        "query_plan": {
            "use_multi_hop": False,
            "use_hyde": False,
            "use_query_expansion": False,
            "fallback_policy": {"entity_filter_to_global": fallback_allowed},
            "budget": {
                "search_limit": 10,
                "rrf_top_k": 10,
                "rerank_candidate_k": 10,
                "final_context_k": 10,
            },
        }
    }


def test_run_search_pipeline_direct_path_runs_tail_nodes():
    calls: list[str] = []

    nodes = SearchPipelineNodes(
        entity_confirm=lambda state, config: {"entity_mode": "none", "entity_filter": ""},
        query_plan=lambda state, config: _plan(),
        rewrite_query=lambda state, config: calls.append("rewrite") or {"rewritten_query": state["query"]},
        table_expand=lambda state, config: calls.append("table") or {"search_results": state["search_results"]},
        rerank=lambda state, config: calls.append("rerank") or {"search_results": state["search_results"]},
        diversify_context=lambda state, config: calls.append("diversify") or {"diversified": True},
        context_expand=lambda state, config: calls.append("context") or {"context_expanded": True},
    )

    state = run_search_pipeline(
        "报销材料？",
        _config(),
        nodes=nodes,
        search_fn=lambda state, config: {
            "search_mode": "hybrid",
            "search_results": [{"chunk_id": 1, "document_id": "doc-1", "score": 0.8}],
        },
        hyde_fn=lambda state, config: {"search_mode_hyde": "disabled", "search_results_hyde": []},
    )

    assert calls == ["rewrite", "table", "rerank", "diversify", "context"]
    assert state["rewritten_query"] == "报销材料？"
    assert state["search_results"][0]["retrieval_paths"] == ["hybrid"]
    assert state["diversified"] is True
    assert state["context_expanded"] is True
    assert state["trace"]["retrieval_wall_ms"] >= 0


def test_run_search_pipeline_post_rerank_fallback_retries_unfiltered():
    seen_filters: list[str] = []

    nodes = SearchPipelineNodes(
        entity_confirm=lambda state, config: {
            "entity_mode": "single",
            "entity_filter": '(entity_name == "A")',
            "matched_entities": ["A"],
        },
        query_plan=lambda state, config: _plan(fallback_allowed=True),
        rewrite_query=lambda state, config: {"rewritten_query": state["query"]},
        table_expand=lambda state, config: {"search_results": state["search_results"]},
        rerank=lambda state, config: {"search_results": state["search_results"]},
        diversify_context=lambda state, config: {},
        context_expand=lambda state, config: {},
    )

    def search_fn(state: dict, config: dict) -> dict:
        entity_filter = state.get("entity_filter", "")
        seen_filters.append(entity_filter)
        return {
            "search_mode": "hybrid_filtered" if entity_filter else "hybrid",
            "search_results": [{
                "chunk_id": 1 if entity_filter else 2,
                "document_id": "doc-1",
                "score": 0.1 if entity_filter else 0.9,
            }],
        }

    state = run_search_pipeline(
        "A 的制度？",
        _config(),
        nodes=nodes,
        search_fn=search_fn,
        hyde_fn=lambda state, config: {"search_mode_hyde": "disabled", "search_results_hyde": []},
    )

    assert seen_filters == ['(entity_name == "A")', ""]
    assert state["search_mode"] == "hybrid_post_rerank_fallback"
    assert state["fallback_info"]["used"] is True
    assert state["fallback_info"]["original_filter"] == '(entity_name == "A")'
    assert state["search_results"][0]["score"] == 0.9
    assert state["trace"]["post_rerank_fallback_ms"] >= 0


def test_should_run_multi_hop_reads_single_flag():
    from app.rag.query.search_pipeline import _should_run_multi_hop

    assert _should_run_multi_hop({"entity_mode": "single"}, "哪些公司", {"use_multi_hop": True}) is True
    assert _should_run_multi_hop({"entity_mode": "broad"}, "报销标准", {"use_multi_hop": False}) is False
