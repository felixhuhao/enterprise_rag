"""Unit tests for the query flavor planner."""

from dataclasses import asdict

from app.rag.query.config import QueryConfig
from app.rag.query.planner import (
    RetrievalBudget,
    build_query_plan,
    get_query_plan,
    plan_allows_entity_fallback,
    plan_budget,
    query_plan_node,
    _clamp_budget,
    _normalize_flavor,
)


def test_balanced_single_keeps_current_defaults():
    plan = build_query_plan("报销标准是什么？", "single", QueryConfig())

    assert plan.retrieval_flavor == "balanced"
    assert plan.use_hyde is True
    assert plan.use_query_expansion is False
    assert plan.use_multi_hop is False
    assert plan.fallback_policy.entity_filter_to_global is True
    assert plan.budget.search_limit == 10
    assert plan.budget.rrf_top_k == 20
    assert plan.budget.rerank_candidate_k == 10
    assert plan.budget.final_context_k == 10
    assert plan.budget.max_context_chars == 8000
    assert plan.budget.per_entity_min_k == 5


def test_balanced_broad_uses_larger_budget_than_single():
    cfg = QueryConfig(search_limit=10, rrf_max_results=20, rerank_max_top_k=10)

    single = build_query_plan("报销标准是什么？", "single", cfg)
    broad = build_query_plan("有哪些公司提到了报销？", "broad", cfg)

    assert broad.budget.search_limit == 20
    assert broad.budget.rrf_top_k == 32
    assert broad.budget.rerank_candidate_k == 20
    assert broad.budget.final_context_k == 8
    assert broad.budget.max_context_chars == 12000
    assert broad.budget.search_limit > single.budget.search_limit


def test_exact_disables_hyde_multi_hop_and_fallback():
    cfg = QueryConfig(retrieval_flavor="exact", use_multi_hop=True, search_limit=20)

    plan = build_query_plan("住宿标准是多少？", "single", cfg)

    assert plan.retrieval_flavor == "exact"
    assert plan.use_hyde is False
    assert plan.use_query_expansion is False
    assert plan.use_multi_hop is False
    assert plan.fallback_policy.entity_filter_to_global is False
    assert plan.budget.search_limit == 8
    assert plan.budget.rrf_top_k == 8
    assert plan.budget.rerank_candidate_k == 8
    assert plan.budget.final_context_k == 3
    assert plan.budget.max_context_chars == 5000
    assert plan.budget.per_entity_min_k == 3


def test_recall_uses_high_coverage_budget():
    cfg = QueryConfig(retrieval_flavor="recall", use_hyde=True, use_multi_hop=True)

    plan = build_query_plan("有哪些相关制度？", "none", cfg)

    assert plan.retrieval_flavor == "recall"
    assert plan.use_hyde is False
    assert plan.use_query_expansion is True
    assert plan.use_multi_hop is True
    assert plan.budget.search_limit == 20
    assert plan.budget.hyde_limit == 0
    assert plan.budget.rrf_top_k == 40
    assert plan.budget.rerank_candidate_k == 30
    assert plan.budget.final_context_k == 8
    assert plan.budget.max_context_chars == 14000
    assert plan.budget.per_entity_min_k == 8


def test_discovery_forces_current_multi_hop_path():
    cfg = QueryConfig(retrieval_flavor="discovery", use_multi_hop=False)

    plan = build_query_plan("哪些公司提到了安全计划？", "broad", cfg)

    assert plan.retrieval_flavor == "discovery"
    assert plan.use_hyde is False
    assert plan.use_query_expansion is False
    assert plan.use_multi_hop is True
    assert plan.fallback_policy.entity_filter_to_global is False
    assert plan.prompt_policy.template == "broad"
    assert plan.budget.search_limit == 10
    assert plan.budget.rrf_top_k == 20
    assert plan.budget.rerank_candidate_k == 10
    assert plan.budget.final_context_k == 10
    assert plan.budget.max_context_chars == 8000
    assert plan.budget.per_entity_min_k == 5


def test_multi_explicit_overrides_per_entity_min_k_for_any_flavor():
    exact = build_query_plan("A 和 B 的制度？", "multi_explicit", QueryConfig(retrieval_flavor="exact"))
    balanced = build_query_plan("A 和 B 的制度？", "multi_explicit", QueryConfig())

    assert exact.budget.search_limit == 8
    assert exact.budget.per_entity_min_k == 8
    assert balanced.budget.search_limit == 10
    assert balanced.budget.per_entity_min_k == 8


def test_budget_clamps_safe_upper_limits():
    budget = _clamp_budget(RetrievalBudget(
        search_limit=50,
        hyde_limit=10,
        rrf_top_k=50,
        rerank_candidate_k=50,
        final_context_k=50,
        max_context_chars=20000,
    ))

    assert budget.search_limit == 40
    assert budget.rrf_top_k == 40
    assert budget.rerank_candidate_k == 30
    assert budget.final_context_k == 30
    assert budget.max_context_chars == 16000


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
    assert out["query_plan"]["fallback_policy"]["entity_filter_to_global"] is False


# ---------------------------------------------------------------------------
# get_query_plan fallback path
# ---------------------------------------------------------------------------


def test_get_query_plan_returns_cached_plan_from_state():
    cached = {"retrieval_flavor": "exact", "use_hyde": False}
    state = {"query": "test", "query_plan": cached}
    assert get_query_plan(state) is cached


def test_get_query_plan_builds_balanced_when_missing():
    state = {"query": "test"}
    config = {"configurable": {"query_config": QueryConfig()}}
    plan = get_query_plan(state, config)
    assert plan["retrieval_flavor"] == "balanced"
    # should not mutate state
    assert "query_plan" not in state


# ---------------------------------------------------------------------------
# plan_allows_entity_fallback
# ---------------------------------------------------------------------------


def test_plan_allows_entity_fallback_balanced():
    state = {"query": "test", "query_plan": {
        "fallback_policy": {"entity_filter_to_global": True},
    }}
    assert plan_allows_entity_fallback(state) is True


def test_plan_allows_entity_fallback_exact():
    state = {"query": "test", "query_plan": {
        "fallback_policy": {"entity_filter_to_global": False},
    }}
    assert plan_allows_entity_fallback(state) is False


def test_plan_allows_entity_fallback_defaults_to_true():
    state = {"query": "test"}  # no query_plan, no fallback_policy
    assert plan_allows_entity_fallback(state, {"configurable": {"query_config": QueryConfig()}}) is True


# ---------------------------------------------------------------------------
# plan_budget
# ---------------------------------------------------------------------------


def test_plan_budget_returns_budget_dict():
    state = {"query": "test", "query_plan": {
        "budget": {"search_limit": 8, "rrf_top_k": 8, "max_context_chars": 5000},
    }}
    budget = plan_budget(state)
    assert budget["search_limit"] == 8
    assert budget["max_context_chars"] == 5000


def test_plan_budget_returns_empty_when_missing():
    state = {"query": "test"}  # no query_plan
    budget = plan_budget(state, {"configurable": {"query_config": QueryConfig()}})
    assert isinstance(budget, dict)
    assert "search_limit" in budget


# ---------------------------------------------------------------------------
# _normalize_flavor
# ---------------------------------------------------------------------------


def test_normalize_flavor_valid_inputs():
    assert _normalize_flavor("balanced") == "balanced"
    assert _normalize_flavor("exact") == "exact"
    assert _normalize_flavor("recall") == "recall"
    assert _normalize_flavor("discovery") == "discovery"


def test_normalize_flavor_invalid_falls_back_to_balanced():
    assert _normalize_flavor("strict_evidence") == "balanced"
    assert _normalize_flavor("unknown") == "balanced"
    assert _normalize_flavor("") == "balanced"


# ---------------------------------------------------------------------------
# discovery + strict_evidence combination
# ---------------------------------------------------------------------------


def test_discovery_with_strict_evidence_disables_fallback():
    cfg = QueryConfig(retrieval_flavor="discovery", strict_evidence=True)

    plan = build_query_plan("哪些公司提到了安全计划？", "broad", cfg)

    assert plan.retrieval_flavor == "discovery"
    assert plan.strict_evidence is True
    assert plan.fallback_policy.entity_filter_to_global is False
    assert plan.use_multi_hop is True


def test_recall_query_expansion_can_be_disabled_by_config():
    cfg = QueryConfig(retrieval_flavor="recall", use_query_expansion=False, use_hyde=True)

    plan = build_query_plan("模糊制度查询", "none", cfg)

    assert plan.use_hyde is False
    assert plan.use_query_expansion is False
