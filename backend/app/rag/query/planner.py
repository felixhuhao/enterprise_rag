"""Central query behavior planner."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import QueryConfig, get_query_config
from app.rag.query.state import QueryState, require_query

RetrievalFlavor = Literal["balanced", "exact", "recall", "discovery"]

VALID_FLAVORS = {"balanced", "exact", "recall", "discovery"}

@dataclass(frozen=True)
class FallbackPolicy:
    entity_filter_to_global: bool
    reason: str


@dataclass(frozen=True)
class RetrievalBudget:
    search_limit: int
    hyde_limit: int
    rrf_top_k: int
    rerank_candidate_k: int
    final_context_k: int
    max_context_chars: int
    per_entity_min_k: int = 5
    reason: str = ""


@dataclass(frozen=True)
class PromptPolicy:
    strict_evidence: bool
    template: str


@dataclass(frozen=True)
class QueryPlan:
    retrieval_flavor: str
    retrieval_breadth: str
    strict_evidence: bool
    use_hyde: bool
    use_query_expansion: bool
    use_multi_hop: bool
    fallback_policy: FallbackPolicy
    budget: RetrievalBudget
    prompt_policy: PromptPolicy


def query_plan_node(state: QueryState, config: RunnableConfig) -> dict:
    """Resolve high-level query controls into one plan plus routing trace."""
    from app.rag.query.control.routing import build_routing_trace, inactive_inline_shadow

    cfg = get_query_config(config)
    query = require_query(state)
    entity_mode = state.get("entity_mode", "none")
    matched = list(state.get("matched_entities") or [])
    flavor, breadth, policy_trace, det_intent, det_decision, det_budget = _resolve_routing(
        query, entity_mode, matched, cfg
    )
    det_bundle = (det_intent, det_decision, det_budget)

    if not _intent_flag("intent.inline_enabled"):
        gated_bundle, inline_shadow = det_bundle, inactive_inline_shadow("inline_disabled")
    elif det_intent.confidence == "high":
        gated_bundle, inline_shadow = det_bundle, inactive_inline_shadow("high_confidence")
    else:
        gated_bundle, inline_shadow = _inline_intent(query, det_bundle, breadth, cfg)

    emitted_bundle = gated_bundle if _intent_flag("intent.active_mode") else det_bundle
    emitted_intent, emitted_decision, emitted_budget = emitted_bundle

    plan = _plan_from_routing(flavor, breadth, emitted_decision, emitted_budget, cfg)
    return {
        "query_plan": asdict(plan),
        "routing_trace": build_routing_trace(
            emitted_intent, breadth, cfg, emitted_decision, inline_shadow, policy_trace
        ),
    }


def build_query_plan(query: str, entity_mode: str, cfg: QueryConfig) -> QueryPlan:
    flavor, breadth, _policy_trace, _inferred, decision, budget = _resolve_routing(
        query, entity_mode, [], cfg
    )
    return _plan_from_routing(flavor, breadth, decision, budget, cfg)


def _resolve_routing(query: str, entity_mode: str, matched_entities: list[str], cfg: QueryConfig):
    """Compute deterministic routing pieces, shared by node and direct builders."""
    from app.rag.query.control.breadth import resolve_breadth
    from app.rag.query.control.inferred import infer_signals

    raw_flavor = _normalize_flavor(cfg.retrieval_flavor)
    breadth = resolve_breadth(raw_flavor)
    flavor = "balanced" if raw_flavor == "discovery" else raw_flavor
    policy_trace = (
        {
            "legacy_retrieval_flavor": raw_flavor,
            "discovery_retired": True,
        }
        if raw_flavor == "discovery"
        else {}
    )
    inferred = infer_signals(query, entity_mode, matched_entities)
    det_intent, decision, budget = _route_bundle_for(inferred, breadth, cfg)
    return flavor, breadth, policy_trace, det_intent, decision, budget


def _route_bundle_for(intent, breadth: str, cfg: QueryConfig):
    """Resolve one planner routing bundle: (intent, decision, budget)."""
    from app.rag.query.control.budget import resolve_budget_profile
    from app.rag.query.control.routing import derive_routing_decision

    budget = resolve_budget_profile(
        breadth, intent.entity_scope, intent.needs_synthesis, cfg, intent.needs_discovery
    )
    decision = derive_routing_decision(intent, breadth, cfg, budget_reason=budget.reason)
    return intent, decision, budget


def _intent_flag(key: str) -> bool:
    """Read a runtime kill-switch flag (sync, cached)."""
    from app.core.runtime_settings import runtime_settings

    return runtime_settings.get_cached(key).strip().lower() == "true"


def _inline_intent(query: str, det_bundle: tuple, breadth: str, cfg: QueryConfig):
    """Dark-wiring seam: classify inline, merge, gate, and trace the proposal."""
    from app.rag.query.control.inferred import merge_intent
    from app.rag.query.control.llm_classifier import classify_intent_inline
    from app.rag.query.control.routing import build_inline_shadow, trust_gate_bundle

    det_intent = det_bundle[0]
    result = classify_intent_inline(query, det_intent)
    merged = merge_intent(det_intent, result.markers)
    merged_bundle = _route_bundle_for(merged, breadth, cfg)
    gated_bundle = trust_gate_bundle(merged_bundle, det_bundle)
    inline_shadow = build_inline_shadow(result, merged_bundle, det_bundle)
    return gated_bundle, inline_shadow


def _plan_from_routing(flavor: str, breadth: str, decision, budget: RetrievalBudget, cfg: QueryConfig) -> QueryPlan:
    fallback_allowed = _breadth_allows_fallback(breadth, cfg)
    fallback_policy = FallbackPolicy(
        entity_filter_to_global=fallback_allowed,
        reason="enabled_by_flavor" if fallback_allowed else "disabled_by_flavor_or_strict_evidence",
    )
    prompt_policy = PromptPolicy(
        strict_evidence=bool(cfg.strict_evidence),
        template=decision.prompt_variant,
    )

    return QueryPlan(
        retrieval_flavor=flavor,
        retrieval_breadth=breadth,
        strict_evidence=bool(cfg.strict_evidence),
        use_hyde=decision.use_hyde,
        use_query_expansion=decision.use_query_expansion,
        use_multi_hop=decision.use_multi_hop,
        fallback_policy=fallback_policy,
        budget=budget,
        prompt_policy=prompt_policy,
    )


def get_query_plan(state: QueryState, config: RunnableConfig | None = None) -> dict:
    """Return resolved plan from state, or build a balanced-compatible fallback."""
    plan = state.get("query_plan")
    if isinstance(plan, dict):
        return plan
    cfg = get_query_config(config or {})
    return asdict(build_query_plan(
        query=require_query(state),
        entity_mode=state.get("entity_mode", "none"),
        cfg=cfg,
    ))


def plan_allows_entity_fallback(state: QueryState, config: RunnableConfig | None = None) -> bool:
    plan = get_query_plan(state, config)
    policy = plan.get("fallback_policy") or {}
    return bool(policy.get("entity_filter_to_global", True))


def plan_budget(state: QueryState, config: RunnableConfig | None = None) -> dict:
    plan = get_query_plan(state, config)
    return plan.get("budget") or {}


def _normalize_flavor(value: str) -> RetrievalFlavor:
    if value in VALID_FLAVORS:
        return value  # type: ignore[return-value]
    return "balanced"


def _breadth_allows_fallback(breadth: str, cfg: QueryConfig) -> bool:
    from app.rag.query.control.breadth import BREADTH_PROFILES

    return BREADTH_PROFILES[breadth].allows_fallback and not cfg.strict_evidence
