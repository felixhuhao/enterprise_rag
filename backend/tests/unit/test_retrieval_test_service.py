"""Unit tests for retrieval-only test runner."""

from app.rag.query.config import QueryConfig
from app.services import retrieval_test_service as svc


def test_run_retrieval_test_returns_strategy_and_paths(monkeypatch):
    monkeypatch.setattr(svc, "get_default_query_config", lambda: QueryConfig(use_table_expand=False))
    monkeypatch.setattr(svc, "entity_confirm_node", lambda state, config: {"confirmed_entity": "", "entity_filter": ""})
    monkeypatch.setattr(svc, "rewrite_query_node", lambda state, config: {"rewritten_query": state["query"]})
    monkeypatch.setattr(svc, "search_node", lambda state, config: {
        "search_mode": "hybrid",
        "search_results": [{
            "chunk_id": 1,
            "document_id": "doc-1",
            "file_title": "制度.md",
            "entity_name": "企业知识库",
            "section_title": "差旅报销",
            "page": 2,
            "source_type": "text",
            "content": "差旅报销需要发票、行程单和审批单。",
            "score": 0.82,
        }],
    })
    monkeypatch.setattr(svc, "hyde_search_node", lambda state, config: {
        "search_mode_hyde": "disabled",
        "search_results_hyde": [],
    })
    monkeypatch.setattr(svc, "table_expand_node", lambda state, config: {
        "search_results": state.get("search_results", []),
    })

    payload = svc.run_retrieval_test(
        "差旅报销需要什么材料？",
        top_k=5,
        use_hybrid=True,
        use_hyde=False,
        use_rerank=False,
    )

    assert payload["strategy"]["top_k"] == 5
    assert payload["strategy"]["hybrid"] is True
    assert payload["strategy"]["hyde"] is False
    assert payload["result_count"] == 1
    assert payload["results"][0]["retrieval_path"] == "Hybrid"
    assert payload["results"][0]["page"] == 2


def test_dense_only_control_uses_dense_search(monkeypatch):
    monkeypatch.setattr(svc, "get_default_query_config", lambda: QueryConfig(use_table_expand=False))
    monkeypatch.setattr(svc, "entity_confirm_node", lambda state, config: {"confirmed_entity": "", "entity_filter": ""})
    monkeypatch.setattr(svc, "rewrite_query_node", lambda state, config: {"rewritten_query": state["query"]})
    monkeypatch.setattr(svc, "_embed_query", lambda query: [0.1, 0.2])
    monkeypatch.setattr(svc, "_dense_only_search", lambda query_dense, entity_filter, cfg: [{
        "chunk_id": 2,
        "document_id": "doc-2",
        "file_title": "安全制度.md",
        "source_type": "text",
        "content": "安全事件需要在 30 分钟内升级。",
        "score": 0.7,
    }])
    monkeypatch.setattr(svc, "hyde_search_node", lambda state, config: {
        "search_mode_hyde": "disabled",
        "search_results_hyde": [],
    })
    monkeypatch.setattr(svc, "table_expand_node", lambda state, config: {
        "search_results": state.get("search_results", []),
    })

    payload = svc.run_retrieval_test(
        "安全事件升级时限？",
        top_k=3,
        use_hybrid=False,
        use_hyde=False,
        use_rerank=False,
    )

    assert payload["strategy"]["hybrid"] is False
    assert payload["strategy"]["dense_weight"] == 1.0
    assert payload["strategy"]["sparse_weight"] == 0.0
    assert payload["strategy"]["search_mode"] == "dense"
    assert payload["results"][0]["retrieval_path"] == "Dense"
