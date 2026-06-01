"""Unit tests for the non-streaming query workflow entry point."""

from app.rag.query import graph
from app.rag.query.config import QueryConfig


def test_run_query_graph_delegates_retrieval_to_shared_pipeline(monkeypatch):
    seen: dict = {}

    def fake_search_pipeline(query: str, config: dict) -> dict:
        seen["query"] = query
        seen["config"] = config
        return {
            "query": query,
            "rewritten_query": "rewritten query",
            "confirmed_entity": "实体A",
            "entity_mode": "single",
            "matched_entities": ["实体A"],
            "per_entity_counts": {"实体A": 1},
            "expanded_queries": [],
            "query_expansion_trace": [],
            "query_plan": {"retrieval_flavor": "balanced", "strict_evidence": False},
            "fallback_info": {"used": False},
            "search_results": [{"chunk_id": 1, "content": "evidence"}],
        }

    monkeypatch.setattr(graph, "run_search_pipeline", fake_search_pipeline)
    monkeypatch.setattr(graph, "build_prompt_node", lambda state, config: {"context_text": "ctx", "context_map": {}})
    monkeypatch.setattr(graph, "generate_answer_node", lambda state: {"answer": "答案"})
    monkeypatch.setattr(graph, "validate_citations_node", lambda state: {"citations": [{"id": "C1"}]})
    monkeypatch.setattr(graph, "groundedness_check_node", lambda state, config: {"groundedness": {"status": "disabled"}})

    cfg = QueryConfig(use_hyde=False)
    out = graph.run_query_graph("原始问题", cfg, {"allowed_document_ids": ["doc-1"]})

    assert seen["query"] == "原始问题"
    assert seen["config"]["configurable"]["query_config"] is cfg
    assert seen["config"]["configurable"]["allowed_document_ids"] == ["doc-1"]
    assert out["answer"] == "答案"
    assert out["results_count"] == 1
    assert out["rewritten_query"] == "rewritten query"
    assert out["entity"] == "实体A"
    assert out["citations"] == [{"id": "C1"}]
    assert out["groundedness"] == {"status": "disabled"}
