"""Derived routing decision via the Design 1 authority chain."""

from __future__ import annotations

from dataclasses import dataclass, field

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
    available = True if breadth == "discovery" else cfg.use_multi_hop
    use_multi_hop = inferred.needs_multi_hop and permitted and available

    if inferred.needs_multi_hop and not permitted:
        vetoes.append(f"{breadth} breadth suppresses multi-hop")
    if inferred.needs_multi_hop and permitted and not available and breadth != "discovery":
        vetoes.append("enable_multi_hop infra veto on multi-hop")

    prompt_variant = _prompt_variant(scope, breadth)
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


def build_routing_trace(
    inferred: InferredSignals,
    breadth: RetrievalBreadth,
    cfg: QueryConfig,
    decision: RoutingDecision,
) -> dict:
    """Trace the three tiers plus the final derived routing decision."""
    return {
        "intent": {
            "entity_scope": inferred.entity_scope,
            "needs_synthesis": inferred.needs_synthesis,
            "needs_discovery": inferred.needs_discovery,
            "needs_multi_hop": inferred.needs_multi_hop,
            "confidence": inferred.confidence,
            "reasons": inferred.reasons,
        },
        "policy": {
            "retrieval_breadth": breadth,
            "strict_evidence": bool(cfg.strict_evidence),
            "vetoes": decision.vetoes,
        },
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
    }


def _prompt_variant(entity_scope: str, breadth: str) -> str:
    if entity_scope == "multi":
        return "multi_entity"
    if breadth == "discovery" or entity_scope == "broad":
        return "broad"
    return "default"
