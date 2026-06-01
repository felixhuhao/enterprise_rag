from app.rag.query.config import QueryConfig
from app.rag.query.direct_search import run_direct_search
from app.rag.query.fallback import fallback_used


def _config(**kwargs) -> dict:
    return {"configurable": {"query_config": QueryConfig(**kwargs)}}


def test_run_direct_search_fuses_primary_and_hyde_results():
    calls: list[str] = []

    def search_fn(state: dict, config: dict) -> dict:
        calls.append("search")
        return {
            "search_results": [
                {"chunk_key": "primary-only", "content": "primary"},
                {"chunk_key": "shared", "content": "primary shared"},
            ],
            "search_mode": "hybrid",
        }

    def hyde_fn(state: dict, config: dict) -> dict:
        calls.append("hyde")
        return {
            "search_results_hyde": [
                {"chunk_key": "shared", "content": "hyde shared"},
                {"chunk_key": "hyde-only", "content": "hyde"},
            ],
            "search_mode_hyde": "hyde",
            "fallback_info": fallback_used("entity_name == 'ACME'"),
        }

    result = run_direct_search(
        {"query": "approval policy", "entity_mode": "none"},
        _config(retrieval_flavor="balanced", use_hyde=True, rrf_max_results=10),
        search_fn=search_fn,
        hyde_fn=hyde_fn,
    )

    assert sorted(calls) == ["hyde", "search"]
    assert result["per_query_counts"] == {"original": 2}
    assert result["search_results_hyde"][0]["chunk_key"] == "shared"
    assert result["search_results"][0]["chunk_key"] == "shared"
    assert result["search_results"][0]["retrieval_paths"] == ["hybrid", "hyde"]
    assert result["fallback_info"]["used"] is True
    assert result["fallback_info"]["original_filter"] == "entity_name == 'ACME'"
    assert result["_rrf_fusion_ms"] >= 0


def test_run_direct_search_disables_hyde_for_exact_flavor():
    calls: list[str] = []

    def search_fn(state: dict, config: dict) -> dict:
        calls.append("search")
        return {
            "search_results": [{"chunk_key": "primary", "content": "primary"}],
            "search_mode": "hybrid",
        }

    def hyde_fn(state: dict, config: dict) -> dict:
        calls.append("hyde")
        return {"search_results_hyde": [{"chunk_key": "hyde"}], "search_mode_hyde": "hyde"}

    result = run_direct_search(
        {"query": "approval policy", "entity_mode": "none"},
        _config(retrieval_flavor="exact", use_hyde=True),
        search_fn=search_fn,
        hyde_fn=hyde_fn,
    )

    assert calls == ["search"]
    assert result["search_results_hyde"] == []
    assert result["search_mode_hyde"] == "disabled"
    assert result["search_results"][0]["retrieval_paths"] == ["hybrid"]


def test_run_direct_search_query_expansion_searches_variants_and_keeps_failed_variant(monkeypatch):
    calls: list[str] = []

    def fake_query_expansion_node(state: dict, config: dict) -> dict:
        return {"expanded_queries": ["expanded one", "expanded two"]}

    def search_fn(state: dict, config: dict) -> dict:
        query = state.get("rewritten_query") or state["query"]
        calls.append(query)
        if query == "expanded two":
            raise RuntimeError("expanded search failed")
        return {
            "search_results": [{"chunk_key": query, "content": query}],
            "search_mode": "hybrid",
        }

    monkeypatch.setattr("app.rag.query.direct_search.query_expansion_node", fake_query_expansion_node)

    result = run_direct_search(
        {"query": "original query", "entity_mode": "none"},
        _config(retrieval_flavor="recall", use_query_expansion=True, rrf_max_results=10),
        search_fn=search_fn,
        hyde_fn=lambda _state, _config: {"search_results_hyde": [{"chunk_key": "should-not-run"}]},
    )

    assert sorted(calls) == ["expanded one", "expanded two", "original query"]
    assert result["expanded_queries"] == ["expanded one", "expanded two"]
    assert result["search_results_hyde"] == []
    assert result["search_modes_expanded"] == ["hybrid", "expanded_1_failed"]
    assert result["per_query_counts"] == {
        "original": 1,
        "expanded_0": 1,
        "expanded_1": 0,
    }
    assert result["query_expansion_trace"] == [
        {"label": "original", "query": "original query", "count": 1},
        {"label": "expanded_1", "query": "expanded one", "count": 1},
        {"label": "expanded_2", "query": "expanded two", "count": 0},
    ]
    assert {row["chunk_key"] for row in result["search_results"]} == {"original query", "expanded one"}
