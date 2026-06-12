from app.rag.query.config import QueryConfig
from app.rag.query.control.budget import resolve_budget_profile
from app.rag.query.control.inferred import infer_signals
from app.rag.query.control.routing import build_routing_trace, derive_routing_decision

CFG = QueryConfig(search_limit=10, rrf_max_results=20, rerank_max_top_k=10, hyde_limit=10)


def _decide(query, entity_mode, breadth, cfg=CFG):
    sig = infer_signals(query, entity_mode, [])
    budget = resolve_budget_profile(breadth, sig.entity_scope, sig.needs_synthesis, cfg)
    return derive_routing_decision(sig, breadth, cfg, budget_reason=budget.reason)


def test_precise_suppresses_multi_hop_and_fallback():
    d = _decide("哪些公司提到了报销？", "broad", "precise")
    assert d.use_multi_hop is False
    assert d.use_entity_fallback is False
    assert "precise breadth suppresses multi-hop" in " ".join(d.vetoes)


def test_broad_does_not_invent_multi_hop():
    d = _decide("报销标准是什么？", "none", "broad")
    assert d.use_multi_hop is False


def test_infra_veto_disables_multi_hop_for_non_discovery():
    cfg = QueryConfig(use_multi_hop=False)
    d = _decide("哪些公司提到了报销？", "broad", "balanced", cfg)
    assert d.use_multi_hop is False


def test_discovery_bypasses_enable_multi_hop():
    cfg = QueryConfig(use_multi_hop=False)
    d = _decide("哪些公司提到了报销？", "broad", "discovery", cfg)
    assert d.use_multi_hop is True


def test_entity_fallback_only_single():
    assert _decide("报销标准", "single", "balanced").use_entity_fallback is True
    assert _decide("报销标准", "multi_explicit", "balanced").use_entity_fallback is False
    assert _decide("报销标准", "broad", "balanced").use_entity_fallback is False


def test_strict_evidence_suppresses_fallback():
    cfg = QueryConfig(strict_evidence=True)
    assert _decide("报销标准", "single", "balanced", cfg).use_entity_fallback is False


def test_prompt_variant_precedence():
    assert _decide("A和B的区别", "multi_explicit", "discovery").prompt_variant == "multi_entity"
    assert _decide("哪些公司", "broad", "discovery").prompt_variant == "broad"
    assert _decide("哪些公司", "broad", "balanced").prompt_variant == "broad"
    assert _decide("报销标准", "single", "balanced").prompt_variant == "default"


def test_hyde_expansion_breadth_owned():
    assert _decide("报销标准", "single", "balanced").use_hyde is True
    assert _decide("报销标准", "single", "broad").use_hyde is False
    assert _decide("报销标准", "single", "broad").use_query_expansion is True


def test_hyde_effective_false_for_multi_scope():
    assert _decide("A和B的报销", "multi_explicit", "balanced").use_hyde is False


def test_trace_has_three_sections():
    sig = infer_signals("哪些公司提到了报销？", "broad", [])
    budget = resolve_budget_profile("precise", sig.entity_scope, sig.needs_synthesis, CFG)
    d = derive_routing_decision(sig, "precise", CFG, budget_reason=budget.reason)
    trace = build_routing_trace(sig, "precise", CFG, d)
    assert set(trace) == {"intent", "policy", "infra", "routing_decision"}
    assert trace["policy"]["retrieval_breadth"] == "precise"
    assert trace["routing_decision"]["use_multi_hop"] is False
