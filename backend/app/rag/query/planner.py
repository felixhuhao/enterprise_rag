"""Central query behavior planner."""

from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass
from typing import Literal

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import QueryConfig, get_query_config
from app.rag.query.state import QueryState, require_query

RetrievalFlavor = Literal["balanced", "exact", "recall", "discovery"]

VALID_FLAVORS = {"balanced", "exact", "recall", "discovery"}

MAX_SEARCH_LIMIT = 40
MAX_RERANK_CANDIDATES = 30
MAX_CONTEXT_CHARS = 16000


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
    from app.rag.query.control.routing import build_routing_trace

    cfg = get_query_config(config)
    query = require_query(state)
    entity_mode = state.get("entity_mode", "none")
    matched = list(state.get("matched_entities") or [])
    flavor, breadth, inferred, decision, budget = _resolve_routing(query, entity_mode, matched, cfg)
    plan = _plan_from_routing(flavor, breadth, decision, budget, cfg)
    return {
        "query_plan": asdict(plan),
        "routing_trace": build_routing_trace(inferred, breadth, cfg, decision),
    }


def build_query_plan(query: str, entity_mode: str, cfg: QueryConfig) -> QueryPlan:
    flavor, breadth, _inferred, decision, budget = _resolve_routing(query, entity_mode, [], cfg)
    return _plan_from_routing(flavor, breadth, decision, budget, cfg)


def _resolve_routing(query: str, entity_mode: str, matched_entities: list[str], cfg: QueryConfig):
    """Compute routing once, shared by direct plan building and graph node execution."""
    from app.rag.query.control.breadth import resolve_breadth
    from app.rag.query.control.budget import resolve_budget_profile
    from app.rag.query.control.inferred import infer_signals
    from app.rag.query.control.routing import derive_routing_decision

    flavor = _normalize_flavor(cfg.retrieval_flavor)
    breadth = resolve_breadth(flavor)
    inferred = infer_signals(query, entity_mode, matched_entities)
    budget = resolve_budget_profile(breadth, inferred.entity_scope, inferred.needs_synthesis, cfg)
    decision = derive_routing_decision(inferred, breadth, cfg, budget_reason=budget.reason)
    return flavor, breadth, inferred, decision, budget


def _plan_from_routing(flavor: str, breadth: str, decision, budget: RetrievalBudget, cfg: QueryConfig) -> QueryPlan:
    from app.rag.query.control.breadth import BREADTH_PROFILES

    fallback_allowed = _breadth_allows_fallback(breadth, cfg)
    fallback_policy = FallbackPolicy(
        entity_filter_to_global=fallback_allowed,
        reason="enabled_by_flavor" if fallback_allowed else "disabled_by_flavor_or_strict_evidence",
    )
    prompt_policy = PromptPolicy(
        strict_evidence=bool(cfg.strict_evidence),
        template=decision.prompt_variant,
    )
    legacy_use_hyde = BREADTH_PROFILES[breadth].sets_hyde and cfg.use_hyde

    return QueryPlan(
        retrieval_flavor=flavor,
        retrieval_breadth=breadth,
        strict_evidence=bool(cfg.strict_evidence),
        use_hyde=legacy_use_hyde,
        use_query_expansion=decision.use_query_expansion,
        use_multi_hop=decision.use_multi_hop,
        fallback_policy=fallback_policy,
        budget=budget,
        prompt_policy=prompt_policy,
    )


def _clamp_budget(budget: RetrievalBudget) -> RetrievalBudget:
    return dataclasses.replace(
        budget,
        search_limit=min(budget.search_limit, MAX_SEARCH_LIMIT),
        rrf_top_k=min(budget.rrf_top_k, MAX_SEARCH_LIMIT),
        rerank_candidate_k=min(budget.rerank_candidate_k, MAX_RERANK_CANDIDATES),
        final_context_k=min(budget.final_context_k, MAX_RERANK_CANDIDATES),
        max_context_chars=min(budget.max_context_chars, MAX_CONTEXT_CHARS),
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
