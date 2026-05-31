from types import SimpleNamespace

from app.rag.query.config import QueryConfig
from app.rag.query.query_expansion import (
    _deterministic_expansions,
    _parse_expanded_queries,
    query_expansion_node,
)


def _config(count: int = 3) -> dict:
    return {"configurable": {"query_config": QueryConfig(query_expansion_count=count)}}


def test_disabled_does_not_generate(monkeypatch):
    called = False

    def fake_invoke(_messages):
        nonlocal called
        called = True
        return SimpleNamespace(content="ignored")

    monkeypatch.setattr("app.rag.query.query_expansion._invoke_expansion_llm", fake_invoke)
    out = query_expansion_node(
        {"query": "差旅标准", "query_plan": {"use_query_expansion": False}},
        _config(),
    )

    assert out == {"expanded_queries": []}
    assert called is False


def test_generates_three_queries(monkeypatch):
    monkeypatch.setattr(
        "app.rag.query.query_expansion._invoke_expansion_llm",
        lambda _messages: SimpleNamespace(content="差旅报销标准\n出差住宿额度\n交通补贴规则"),
    )

    out = query_expansion_node(
        {"query": "差旅标准", "query_plan": {"use_query_expansion": True}},
        _config(count=3),
    )

    assert out["expanded_queries"] == ["差旅报销标准", "出差住宿额度", "交通补贴规则"]


def test_truncates_to_count(monkeypatch):
    monkeypatch.setattr(
        "app.rag.query.query_expansion._invoke_expansion_llm",
        lambda _messages: SimpleNamespace(content="A\nB\nC\nD\nE"),
    )

    out = query_expansion_node(
        {"query": "Q", "query_plan": {"use_query_expansion": True}},
        _config(count=3),
    )

    assert out["expanded_queries"] == ["A", "B", "C"]


def test_llm_exception_returns_empty(monkeypatch):
    def fail(_messages):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.rag.query.query_expansion._invoke_expansion_llm", fail)

    out = query_expansion_node(
        {"query": "差旅标准", "query_plan": {"use_query_expansion": True}},
        _config(),
    )

    assert out == {"expanded_queries": []}


def test_amount_approval_query_gets_deterministic_expansion(monkeypatch):
    monkeypatch.setattr(
        "app.rag.query.query_expansion._invoke_expansion_llm",
        lambda _messages: SimpleNamespace(content="审批金额限制\n审批权限金额标准\n各制度费用门槛"),
    )

    out = query_expansion_node(
        {"query": "有哪些涉及金额审批的阈值？", "query_plan": {"use_query_expansion": True}},
        _config(count=3),
    )

    assert out["expanded_queries"][0].startswith("金额审批阈值")
    assert len(out["expanded_queries"]) == 3


def test_deterministic_expansion_requires_amount_and_approval_terms():
    assert _deterministic_expansions("金额审批阈值")
    assert _deterministic_expansions("金额标准") == []
    assert _deterministic_expansions("审批流程") == []


def test_parse_filters_empty_numbering_duplicates_and_original():
    parsed = _parse_expanded_queries(
        "\n1. 差旅标准\n2、差旅报销标准\n- 3) 差旅报销标准\n4. 住宿额度\n",
        "差旅标准",
        3,
    )

    assert parsed == ["差旅报销标准", "住宿额度"]
