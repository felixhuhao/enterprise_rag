"""Unit tests for the query flavor planner."""

from dataclasses import asdict

from app.core.runtime_settings import runtime_settings
from app.rag.query.config import QueryConfig
from app.rag.query.control import llm_classifier
from app.rag.query.control.llm_classifier import ClassifyResult, LlmMarkers
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
    assert plan.retrieval_breadth == "balanced"
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


def test_balanced_synthesis_uses_larger_candidate_budget():
    cfg = QueryConfig(search_limit=10, rrf_max_results=20, rerank_max_top_k=10)

    plan = build_query_plan("安全事件响应和运维故障响应有什么关联和区别？", "single", cfg)

    assert plan.retrieval_flavor == "balanced"
    assert plan.retrieval_breadth == "balanced"
    assert plan.budget.search_limit == 20
    assert plan.budget.rrf_top_k == 32
    assert plan.budget.rerank_candidate_k == 20
    assert plan.budget.final_context_k == 10
    assert plan.budget.max_context_chars == 10000
    assert plan.budget.reason == "balanced_synthesis"


def test_exact_disables_hyde_multi_hop_and_fallback():
    cfg = QueryConfig(retrieval_flavor="exact", use_multi_hop=True, search_limit=20)

    plan = build_query_plan("住宿标准是多少？", "single", cfg)

    assert plan.retrieval_flavor == "exact"
    assert plan.retrieval_breadth == "precise"
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
    assert plan.retrieval_breadth == "broad"
    assert plan.use_hyde is False
    assert plan.use_query_expansion is True
    assert plan.use_multi_hop is False
    assert plan.budget.search_limit == 20
    assert plan.budget.hyde_limit == 0
    assert plan.budget.rrf_top_k == 40
    assert plan.budget.rerank_candidate_k == 30
    assert plan.budget.final_context_k == 8
    assert plan.budget.max_context_chars == 14000
    assert plan.budget.per_entity_min_k == 8


def test_discovery_input_retires_to_balanced_policy():
    cfg = QueryConfig(retrieval_flavor="discovery", use_multi_hop=False)

    plan = build_query_plan("哪些公司提到了安全计划？", "broad", cfg)

    assert plan.retrieval_flavor == "balanced"
    assert plan.retrieval_breadth == "balanced"
    assert plan.use_hyde is True
    assert plan.use_query_expansion is False
    assert plan.use_multi_hop is False
    assert plan.fallback_policy.entity_filter_to_global is True
    assert plan.prompt_policy.template == "broad"
    assert plan.budget.reason == "balanced_discovery"
    assert plan.budget.search_limit == 20
    assert plan.budget.rrf_top_k == 32
    assert plan.budget.rerank_candidate_k == 20
    assert plan.budget.final_context_k == 8
    assert plan.budget.max_context_chars == 12000
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

    assert out["query_plan"]["retrieval_flavor"] == "balanced"
    assert out["query_plan"]["retrieval_breadth"] == "balanced"
    assert out["query_plan"]["use_multi_hop"] is True
    assert out["query_plan"]["fallback_policy"]["entity_filter_to_global"] is True
    assert out["query_plan"]["budget"]["reason"] == "balanced_discovery"
    assert out["routing_trace"]["policy"]["retrieval_breadth"] == "balanced"
    assert out["routing_trace"]["policy"]["legacy_retrieval_flavor"] == "discovery"
    assert out["routing_trace"]["policy"]["discovery_retired"] is True
    assert out["routing_trace"]["routing_decision"]["use_multi_hop"] is True
    assert out["routing_trace"]["intent"]["source"] == "deterministic"
    assert out["routing_trace"]["intent"]["fallback_used"] is False
    assert out["routing_trace"]["intent"]["confidence"] == "high"
    assert out["routing_trace"]["inline_shadow"]["ran"] is False
    assert out["routing_trace"]["inline_shadow"]["fallback_reason"] == "none"
    assert out["routing_trace"]["inline_shadow"]["skip_reason"] == "inline_disabled"


def _set_flags(monkeypatch, *, inline, active):
    monkeypatch.setitem(runtime_settings._cache, "intent.inline_enabled", "true" if inline else "false")
    monkeypatch.setitem(runtime_settings._cache, "intent.active_mode", "true" if active else "false")


def _divergent_high(reason="none", markers=True):
    payload = LlmMarkers(needs_synthesis=True, needs_discovery=False, confidence="high", reasons=["x"])
    return lambda q, d: ClassifyResult(
        markers=payload if markers else None,
        fallback_reason=reason,
        latency_ms=5,
    )


_STATE = {"query": "报销标准是什么？", "entity_mode": "single"}
_CONFIG = {"configurable": {"query_config": QueryConfig()}}


def test_inline_on_active_off_preserves_plan(monkeypatch):
    monkeypatch.setattr(llm_classifier, "classify_intent_inline", _divergent_high())
    _set_flags(monkeypatch, inline=False, active=False)
    baseline = query_plan_node(_STATE, _CONFIG)["query_plan"]

    _set_flags(monkeypatch, inline=True, active=False)
    out = query_plan_node(_STATE, _CONFIG)

    assert out["query_plan"] == baseline
    assert out["routing_trace"]["inline_shadow"]["ran"] is True
    assert out["routing_trace"]["inline_shadow"]["activatable_diverged"] is True


def test_inline_skips_classifier_for_high_confidence_deterministic(monkeypatch):
    calls = []
    monkeypatch.setattr(
        llm_classifier,
        "classify_intent_inline",
        lambda q, d: calls.append(1) or ClassifyResult(None, "none", 0),
    )
    _set_flags(monkeypatch, inline=True, active=True)

    out = query_plan_node(
        {"query": "哪些公司提到了安全计划？", "entity_mode": "broad"},
        _CONFIG,
    )

    assert calls == []
    shadow = out["routing_trace"]["inline_shadow"]
    assert shadow["ran"] is False
    assert shadow["fallback_reason"] == "none"
    assert shadow["skip_reason"] == "high_confidence"


def test_inline_runs_classifier_below_high_confidence(monkeypatch):
    calls = []
    monkeypatch.setattr(
        llm_classifier,
        "classify_intent_inline",
        lambda q, d: calls.append(1) or _divergent_high()(q, d),
    )
    _set_flags(monkeypatch, inline=True, active=True)

    out = query_plan_node(_STATE, _CONFIG)

    assert calls == [1]
    assert out["routing_trace"]["inline_shadow"]["ran"] is True
    assert out["routing_trace"]["intent"]["source"] == "llm_escalated"


def test_activation_drives_when_merged_confidence_high(monkeypatch):
    monkeypatch.setattr(llm_classifier, "classify_intent_inline", _divergent_high())
    _set_flags(monkeypatch, inline=False, active=False)
    baseline = query_plan_node(_STATE, _CONFIG)["query_plan"]

    _set_flags(monkeypatch, inline=True, active=True)
    out = query_plan_node(_STATE, _CONFIG)

    assert (
        out["query_plan"]["use_query_expansion"] != baseline["use_query_expansion"]
        or out["query_plan"]["budget"] != baseline["budget"]
    )
    assert out["routing_trace"]["routing_decision"]["answer_shape"] == "bullets_or_table"
    assert out["routing_trace"]["intent"]["source"] == "llm_escalated"


def test_failure_fallback_below_high_stays_deterministic(monkeypatch):
    monkeypatch.setattr(
        llm_classifier,
        "classify_intent_inline",
        _divergent_high(reason="timeout", markers=False),
    )
    _set_flags(monkeypatch, inline=False, active=False)
    baseline = query_plan_node(_STATE, _CONFIG)["query_plan"]

    _set_flags(monkeypatch, inline=True, active=True)
    out = query_plan_node(_STATE, _CONFIG)

    assert out["query_plan"] == baseline
    shadow = out["routing_trace"]["inline_shadow"]
    assert shadow["ran"] is True
    assert shadow["fallback_used"] is True
    assert shadow["fallback_reason"] == "timeout"
    assert shadow["activatable_diverged"] is False
    assert out["routing_trace"]["intent"]["fallback_used"] is False


def test_kill_switch_does_not_call_classifier(monkeypatch):
    calls = []
    monkeypatch.setattr(
        llm_classifier,
        "classify_intent_inline",
        lambda q, d: calls.append(1) or ClassifyResult(None, "none", 0),
    )
    _set_flags(monkeypatch, inline=False, active=False)

    out = query_plan_node(_STATE, _CONFIG)

    assert calls == []
    assert out["routing_trace"]["inline_shadow"]["ran"] is False
    assert out["routing_trace"]["inline_shadow"]["skip_reason"] == "inline_disabled"


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
    assert plan["retrieval_breadth"] == "balanced"
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


def test_retired_discovery_with_strict_evidence_disables_fallback():
    cfg = QueryConfig(retrieval_flavor="discovery", strict_evidence=True)

    plan = build_query_plan("哪些公司提到了安全计划？", "broad", cfg)

    assert plan.retrieval_flavor == "balanced"
    assert plan.retrieval_breadth == "balanced"
    assert plan.strict_evidence is True
    assert plan.fallback_policy.entity_filter_to_global is False
    assert plan.use_multi_hop is True


def test_recall_query_expansion_can_be_disabled_by_config():
    cfg = QueryConfig(retrieval_flavor="recall", use_query_expansion=False, use_hyde=True)

    plan = build_query_plan("模糊制度查询", "none", cfg)

    assert plan.use_hyde is False
    assert plan.use_query_expansion is False


def test_use_multi_hop_is_effective_for_keywordless_configs():
    p = build_query_plan(
        "有哪些相关制度？",
        "none",
        QueryConfig(retrieval_flavor="recall", use_multi_hop=True),
    )
    assert p.use_multi_hop is False

    p2 = build_query_plan("最新的制度内容", "none", QueryConfig(retrieval_flavor="discovery"))
    assert p2.use_multi_hop is False
    assert p2.retrieval_flavor == "balanced"
    assert p2.retrieval_breadth == "balanced"

    p3 = build_query_plan("哪些公司提到了报销？", "broad", QueryConfig(retrieval_flavor="discovery"))
    assert p3.use_multi_hop is True
    assert p3.retrieval_flavor == "balanced"
    assert p3.retrieval_breadth == "balanced"


def test_hyde_two_value_compat_for_multi_entity():
    from app.rag.query.control.budget import resolve_budget_profile
    from app.rag.query.control.inferred import infer_signals
    from app.rag.query.control.routing import derive_routing_decision

    cfg = QueryConfig()
    q = "A公司和B公司的报销"
    plan = build_query_plan(q, "multi_explicit", cfg)
    assert plan.use_hyde is True

    inferred = infer_signals(q, "multi_explicit", [])
    budget = resolve_budget_profile(
        "balanced", inferred.entity_scope, inferred.needs_synthesis, cfg, inferred.needs_discovery
    )
    decision = derive_routing_decision(inferred, "balanced", cfg, budget_reason=budget.reason)
    assert decision.use_hyde is False
