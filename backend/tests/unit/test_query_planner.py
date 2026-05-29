"""Unit tests for the query flavor planner."""

from app.rag.query.config import QueryConfig
from app.rag.query.planner import build_query_plan, query_plan_node


def test_balanced_keeps_current_defaults():
    plan = build_query_plan("报销标准是什么？", "single", QueryConfig())

    assert plan.retrieval_flavor == "balanced"
    assert plan.use_hyde is True
    assert plan.use_query_expansion is False
    assert plan.use_multi_hop is False
    assert plan.fallback_policy.entity_filter_to_global is True
    assert plan.budget.search_limit == 10


def test_exact_disables_hyde_multi_hop_and_fallback():
    cfg = QueryConfig(retrieval_flavor="exact", use_multi_hop=True, search_limit=20)

    plan = build_query_plan("住宿标准是多少？", "single", cfg)

    assert plan.retrieval_flavor == "exact"
    assert plan.use_hyde is False
    assert plan.use_multi_hop is False
    assert plan.fallback_policy.entity_filter_to_global is False
    assert plan.budget.search_limit == 8
    assert plan.budget.final_context_k == 3


def test_recall_is_balanced_for_now():
    cfg = QueryConfig(retrieval_flavor="recall", use_hyde=True, use_multi_hop=True)

    plan = build_query_plan("有哪些相关制度？", "none", cfg)

    assert plan.retrieval_flavor == "recall"
    assert plan.use_hyde is True
    assert plan.use_query_expansion is False
    assert plan.use_multi_hop is True


def test_discovery_forces_current_multi_hop_path():
    cfg = QueryConfig(retrieval_flavor="discovery", use_multi_hop=False)

    plan = build_query_plan("哪些公司提到了安全计划？", "broad", cfg)

    assert plan.retrieval_flavor == "discovery"
    assert plan.use_hyde is False
    assert plan.use_multi_hop is True
    assert plan.prompt_policy.template == "broad"


def test_strict_evidence_is_independent_policy():
    cfg = QueryConfig(retrieval_flavor="balanced", strict_evidence=True)

    plan = build_query_plan("差旅标准是什么？", "single", cfg)

    assert plan.retrieval_flavor == "balanced"
    assert plan.strict_evidence is True
    assert plan.prompt_policy.strict_evidence is True
    assert plan.fallback_policy.entity_filter_to_global is False


def test_query_plan_node_returns_plain_dict():
    out = query_plan_node(
        {"query": "哪些公司提到了安全计划？", "entity_mode": "broad"},
        {"configurable": {"query_config": QueryConfig(retrieval_flavor="discovery")}},
    )

    assert out["query_plan"]["retrieval_flavor"] == "discovery"
    assert out["query_plan"]["use_multi_hop"] is True
    assert out["query_plan"]["fallback_policy"]["entity_filter_to_global"] is True
