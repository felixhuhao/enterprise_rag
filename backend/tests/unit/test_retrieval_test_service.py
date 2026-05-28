"""Unit tests for retrieval-only test runner."""

from app.rag.query.config import QueryConfig
from app.services import retrieval_test_service as svc


def _noop_entity_confirm(state, config):
    return {"confirmed_entity": "", "entity_filter": "", "entity_mode": "none", "matched_entities": [], "per_entity_counts": {}}


def _noop_rewrite(state, config):
    return {"rewritten_query": state["query"]}


def _noop_table_expand(state, config):
    return {"search_results": state.get("search_results", [])}


_SAMPLE_HIT = {
    "chunk_id": 1,
    "document_id": "doc-1",
    "file_title": "制度.md",
    "entity_name": "企业知识库",
    "section_title": "差旅报销",
    "page": 2,
    "source_type": "text",
    "content": "差旅报销需要发票、行程单和审批单。",
    "score": 0.82,
}


def test_run_retrieval_test_returns_strategy_and_paths(monkeypatch):
    monkeypatch.setattr(svc, "get_default_query_config", lambda: QueryConfig(use_table_expand=False))
    monkeypatch.setattr(svc, "_entity_confirm_node", _noop_entity_confirm)
    monkeypatch.setattr(svc, "_rewrite_query_node", _noop_rewrite)
    monkeypatch.setattr(svc, "_search_node", lambda state, config: {
        "search_mode": "hybrid",
        "search_results": [_SAMPLE_HIT],
    })
    monkeypatch.setattr(svc, "_hyde_search_node", lambda state, config: {
        "search_mode_hyde": "disabled",
        "search_results_hyde": [],
    })
    monkeypatch.setattr(svc, "_table_expand_node", _noop_table_expand)

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
    monkeypatch.setattr(svc, "_entity_confirm_node", _noop_entity_confirm)
    monkeypatch.setattr(svc, "_rewrite_query_node", _noop_rewrite)
    monkeypatch.setattr(svc, "_embed_query", lambda query: [0.1, 0.2])
    monkeypatch.setattr(svc, "_dense_only_search_limited", lambda qd, ef, lim: [{
        "chunk_id": 2,
        "document_id": "doc-2",
        "file_title": "安全制度.md",
        "source_type": "text",
        "content": "安全事件需要在 30 分钟内升级。",
        "score": 0.7,
    }])
    monkeypatch.setattr(svc, "_hyde_search_node", lambda state, config: {
        "search_mode_hyde": "disabled",
        "search_results_hyde": [],
    })
    monkeypatch.setattr(svc, "_table_expand_node", _noop_table_expand)

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


def test_dense_only_multi_entity_keeps_entity_filters(monkeypatch):
    monkeypatch.setattr(svc, "get_default_query_config", lambda: QueryConfig(search_limit=4, use_table_expand=False))
    monkeypatch.setattr(svc, "_entity_confirm_node", lambda state, config: {
        "confirmed_entity": "实体A",
        "entity_filter": "",
        "entity_mode": "multi_explicit",
        "matched_entities": ["实体A", "实体B"],
        "per_entity_counts": {},
    })
    monkeypatch.setattr(svc, "_rewrite_query_node", _noop_rewrite)
    monkeypatch.setattr(svc, "_embed_query", lambda query: [0.1, 0.2])
    monkeypatch.setattr(svc, "_hyde_search_node", lambda state, config: {
        "search_mode_hyde": "disabled",
        "search_results_hyde": [],
    })
    monkeypatch.setattr(svc, "_table_expand_node", _noop_table_expand)

    seen_filters: list[str] = []

    def fake_dense(_query_dense, entity_filter, limit):
        seen_filters.append(entity_filter)
        entity = "实体A" if "实体A" in entity_filter else "实体B"
        return [{
            "chunk_id": 10 if entity == "实体A" else 20,
            "document_id": f"doc-{entity}",
            "file_title": f"{entity}.md",
            "entity_name": entity,
            "source_type": "text",
            "content": f"{entity} 的制度内容",
            "score": 0.8,
        }]

    monkeypatch.setattr(svc, "_dense_only_search_limited", fake_dense)

    payload = svc.run_retrieval_test(
        "实体A 和 实体B 的制度差异？",
        top_k=4,
        use_hybrid=False,
        use_hyde=False,
        use_rerank=False,
    )

    assert seen_filters == ['entity_name == "实体A"', 'entity_name == "实体B"']
    assert payload["strategy"]["search_mode"] == "multi_dense_filtered"
    assert payload["per_entity_counts"] == {"实体A": 1, "实体B": 1}
    assert {row["entity_name"] for row in payload["results"]} == {"实体A", "实体B"}
