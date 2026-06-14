"""Derived routing decision and inline-shadow helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.rag.query.config import QueryConfig
from app.rag.query.control.breadth import BREADTH_PROFILES, RetrievalBreadth
from app.rag.query.control.inferred import InferredSignals


@dataclass(frozen=True)
class RoutingDecision:
    use_hyde: bool
    use_query_expansion: bool
    use_multi_hop: bool
    use_entity_fallback: bool
    budget_reason: str
    prompt_variant: str
    answer_shape: str
    steps: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)


_EXECUTION_DECISION_FIELDS = (
    "use_hyde",
    "use_query_expansion",
    "use_multi_hop",
    "use_entity_fallback",
    "budget_reason",
    "prompt_variant",
    "answer_shape",
    "steps",
)


def derive_routing_decision(
    inferred: InferredSignals,
    breadth: RetrievalBreadth,
    cfg: QueryConfig,
    *,
    budget_reason: str,
) -> RoutingDecision:
    """Derive effective execution strategy from inferred intent, breadth, and infra."""
    profile = BREADTH_PROFILES[breadth]
    scope = inferred.entity_scope
    reasons = list(inferred.reasons)
    vetoes: list[str] = []

    use_hyde = profile.sets_hyde and cfg.use_hyde and scope != "multi"
    use_query_expansion = profile.sets_expansion and cfg.use_query_expansion
    use_entity_fallback = scope == "single" and profile.allows_fallback and not cfg.strict_evidence

    permitted = profile.permits_multi_hop
    available = cfg.use_multi_hop
    use_multi_hop = inferred.needs_multi_hop and permitted and available

    if inferred.needs_multi_hop and not permitted:
        vetoes.append(f"{breadth} breadth suppresses multi-hop")
    if inferred.needs_multi_hop and permitted and not available:
        vetoes.append("enable_multi_hop infra veto on multi-hop")

    prompt_variant = _prompt_variant(scope, breadth, inferred.needs_discovery)
    answer_shape = "bullets_or_table" if inferred.needs_synthesis else "prose"

    steps: list[str] = []
    if scope == "multi":
        steps.append("multi_entity")
    if use_multi_hop:
        steps.append("multi_hop")

    return RoutingDecision(
        use_hyde=use_hyde,
        use_query_expansion=use_query_expansion,
        use_multi_hop=use_multi_hop,
        use_entity_fallback=use_entity_fallback,
        budget_reason=budget_reason,
        prompt_variant=prompt_variant,
        answer_shape=answer_shape,
        steps=steps,
        reasons=reasons,
        vetoes=vetoes,
    )


def trust_gate(
    intent: InferredSignals,
    inferred_decision: RoutingDecision,
    design1_decision: RoutingDecision,
) -> RoutingDecision:
    """Trust the inferred route only when the shared activation predicate passes."""
    return inferred_decision if activatable(intent) else design1_decision


def activatable(intent: InferredSignals) -> bool:
    """A route may drive only at high confidence and never on a fallback."""
    return intent.confidence == "high" and not intent.fallback_used


def trust_gate_bundle(merged_bundle: tuple, det_bundle: tuple) -> tuple:
    """Select a whole (intent, decision, budget) bundle."""
    merged_intent = merged_bundle[0]
    return merged_bundle if activatable(merged_intent) else det_bundle


def build_inline_shadow(result, merged_bundle: tuple, det_bundle: tuple) -> dict:
    """Record the raw pre-gate LLM proposal vs the deterministic route."""
    merged_intent, merged_decision, _merged_budget = merged_bundle
    _det_intent, det_decision, _det_budget = det_bundle
    proposal_diverged = decision_execution_dict(merged_decision) != decision_execution_dict(det_decision)
    return {
        "ran": True,
        "fallback_used": result.markers is None,
        "fallback_reason": result.fallback_reason,
        "latency_ms": result.latency_ms,
        "confidence": merged_intent.confidence,
        "merged_markers": {
            "needs_synthesis": merged_intent.needs_synthesis,
            "needs_discovery": merged_intent.needs_discovery,
            "needs_multi_hop": merged_intent.needs_multi_hop,
        },
        "merged_reasons": list(merged_intent.reasons),
        "merged_source": merged_intent.source,
        "proposal_diverged": proposal_diverged,
        "activatable_diverged": proposal_diverged and activatable(merged_intent),
    }


def inactive_inline_shadow(skip_reason: str = "inline_disabled") -> dict:
    """Trace block when the inline classifier did not run."""
    return {"ran": False, "fallback_reason": "none", "skip_reason": skip_reason}


def build_routing_trace(
    inferred: InferredSignals,
    breadth: RetrievalBreadth,
    cfg: QueryConfig,
    decision: RoutingDecision,
    inline_shadow: dict,
    policy_trace: dict | None = None,
) -> dict:
    """Trace the three tiers, emitted decision, and inline-shadow record."""
    policy = {
        "retrieval_breadth": breadth,
        "strict_evidence": bool(cfg.strict_evidence),
        "vetoes": decision.vetoes,
    }
    if policy_trace:
        policy.update(policy_trace)
    return {
        "intent": {
            "entity_scope": inferred.entity_scope,
            "needs_synthesis": inferred.needs_synthesis,
            "needs_discovery": inferred.needs_discovery,
            "needs_multi_hop": inferred.needs_multi_hop,
            "confidence": inferred.confidence,
            "source": inferred.source,
            "fallback_used": inferred.fallback_used,
            "reasons": inferred.reasons,
        },
        "policy": policy,
        "infra": {
            "enable_hyde": bool(cfg.use_hyde),
            "enable_query_expansion": bool(cfg.use_query_expansion),
            "enable_multi_hop": bool(cfg.use_multi_hop),
        },
        "routing_decision": {
            "use_hyde": decision.use_hyde,
            "use_query_expansion": decision.use_query_expansion,
            "use_multi_hop": decision.use_multi_hop,
            "use_entity_fallback": decision.use_entity_fallback,
            "budget_reason": decision.budget_reason,
            "prompt_variant": decision.prompt_variant,
            "answer_shape": decision.answer_shape,
            "steps": decision.steps,
            "reasons": decision.reasons,
        },
        "inline_shadow": inline_shadow,
    }


def decision_execution_dict(decision: RoutingDecision | Mapping[str, Any]) -> dict:
    """Return only fields that affect routing behavior, not trace metadata."""
    if isinstance(decision, Mapping):
        return {field: decision.get(field) for field in _EXECUTION_DECISION_FIELDS}
    return {field: getattr(decision, field) for field in _EXECUTION_DECISION_FIELDS}


def _prompt_variant(entity_scope: str, breadth: str, needs_discovery: bool) -> str:
    if entity_scope == "multi":
        return "multi_entity"
    if breadth == "precise":
        return "default"
    if needs_discovery or entity_scope == "broad":
        return "broad"
    return "default"
