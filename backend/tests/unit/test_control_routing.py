from dataclasses import dataclass

from app.rag.query.config import QueryConfig
from app.rag.query.control.budget import resolve_budget_profile
from app.rag.query.control.inferred import InferredSignals, infer_signals
from app.rag.query.control.routing import (
    RoutingDecision,
    activatable,
    build_inline_shadow,
    build_routing_trace,
    derive_routing_decision,
    inactive_inline_shadow,
    trust_gate,
    trust_gate_bundle,
)

CFG = QueryConfig(search_limit=10, rrf_max_results=20, rerank_max_top_k=10, hyde_limit=10)


@dataclass
class _FakeResult:
    markers: object
    fallback_reason: str
    latency_ms: int


def _routing_decision(**overrides):
    base = dict(
        use_hyde=True,
        use_query_expansion=False,
        use_multi_hop=False,
        use_entity_fallback=True,
        budget_reason="balanced",
        prompt_variant="default",
        answer_shape="prose",
        steps=[],
        reasons=[],
        vetoes=[],
    )
    base.update(overrides)
    return RoutingDecision(**base)


def _intent(confidence="high", fallback_used=False, needs_synthesis=False):
    return InferredSignals(
        "single",
        needs_synthesis,
        False,
        False,
        confidence=confidence,
        fallback_used=fallback_used,
        source="llm_escalated",
    )


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


def test_build_routing_trace_keys_include_inline_shadow():
    sig = infer_signals("哪些公司提到了报销？", "broad", [])
    budget = resolve_budget_profile("precise", sig.entity_scope, sig.needs_synthesis, CFG)
    d = derive_routing_decision(sig, "precise", CFG, budget_reason=budget.reason)
    trace = build_routing_trace(sig, "precise", CFG, d, inactive_inline_shadow())
    assert set(trace) == {"intent", "policy", "infra", "routing_decision", "inline_shadow"}
    assert trace["policy"]["retrieval_breadth"] == "precise"
    assert trace["routing_decision"]["use_multi_hop"] is False
    assert trace["inline_shadow"]["ran"] is False


def test_trust_gate_high_confidence_uses_inferred():
    inferred = RoutingDecision(True, True, True, True, "inferred", "broad", "prose")
    design1 = RoutingDecision(False, False, False, False, "design1", "default", "prose")
    intent = infer_signals("所有公司的报销标准", "broad", [])

    assert trust_gate(intent, inferred, design1) is inferred


def test_trust_gate_below_high_uses_design1():
    inferred = RoutingDecision(True, True, True, True, "inferred", "broad", "prose")
    design1 = RoutingDecision(False, False, False, False, "design1", "default", "prose")
    intent = infer_signals("报销标准是什么", "single", [])

    assert trust_gate(intent, inferred, design1) is design1


def test_trust_gate_uses_shared_activatable_predicate_for_fallback():
    inferred = _routing_decision(use_query_expansion=True)
    design1 = _routing_decision(use_query_expansion=False)

    assert trust_gate(_intent("high", fallback_used=True), inferred, design1) is design1


def test_activatable_requires_high_and_not_fallback():
    assert activatable(_intent("high")) is True
    assert activatable(_intent("medium")) is False
    assert activatable(_intent("high", fallback_used=True)) is False


def test_trust_gate_bundle_selects_merged_when_activatable():
    det = (_intent("high"), "DET_DEC", "DET_BUD")
    merged = (_intent("high", needs_synthesis=True), "MERGED_DEC", "MERGED_BUD")

    assert trust_gate_bundle(merged, det) is merged


def test_trust_gate_bundle_falls_back_when_not_activatable():
    det = (_intent("high"), "DET_DEC", "DET_BUD")
    merged_lo = (_intent("medium", needs_synthesis=True), "MERGED_DEC", "MERGED_BUD")
    merged_fb = (_intent("high", fallback_used=True), "MERGED_DEC", "MERGED_BUD")

    assert trust_gate_bundle(merged_lo, det) is det
    assert trust_gate_bundle(merged_fb, det) is det


def test_build_inline_shadow_diverged_high_is_activatable():
    det_int = _intent("high")
    det_dec = _routing_decision(use_query_expansion=False)
    merged_int = _intent("high", needs_synthesis=True)
    merged_dec = _routing_decision(use_query_expansion=True)
    shadow = build_inline_shadow(
        _FakeResult(markers=object(), fallback_reason="none", latency_ms=42),
        (merged_int, merged_dec, "B"),
        (det_int, det_dec, "B"),
    )

    assert shadow["ran"] is True
    assert shadow["fallback_used"] is False
    assert shadow["proposal_diverged"] is True
    assert shadow["activatable_diverged"] is True
    assert shadow["latency_ms"] == 42
    assert shadow["merged_markers"]["needs_synthesis"] is True


def test_build_inline_shadow_diverged_low_not_activatable():
    det_int = _intent("high")
    merged_int = _intent("medium", needs_synthesis=True)
    shadow = build_inline_shadow(
        _FakeResult(markers=object(), fallback_reason="none", latency_ms=7),
        (merged_int, _routing_decision(use_query_expansion=True), "B"),
        (det_int, _routing_decision(use_query_expansion=False), "B"),
    )

    assert shadow["proposal_diverged"] is True
    assert shadow["activatable_diverged"] is False


def test_build_inline_shadow_converged():
    det_int = _intent("high")
    dec = _routing_decision(use_query_expansion=False)
    shadow = build_inline_shadow(
        _FakeResult(markers=object(), fallback_reason="none", latency_ms=1),
        (_intent("high"), dec, "B"),
        (det_int, dec, "B"),
    )

    assert shadow["proposal_diverged"] is False
    assert shadow["activatable_diverged"] is False


def test_inactive_inline_shadow():
    assert inactive_inline_shadow() == {
        "ran": False,
        "fallback_reason": "none",
        "skip_reason": "inline_disabled",
    }
    assert inactive_inline_shadow("high_confidence")["skip_reason"] == "high_confidence"


def test_build_routing_trace_embeds_inline_shadow():
    sig = _intent("high")
    d = _routing_decision()
    shadow = {"ran": True, "fallback_reason": "none", "proposal_diverged": True}
    trace = build_routing_trace(sig, "balanced", CFG, d, shadow)

    assert trace["intent"]["source"] == "llm_escalated"
    assert trace["inline_shadow"] is shadow
