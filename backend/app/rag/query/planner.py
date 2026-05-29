"""Central query behavior planner."""

from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass
from typing import Literal

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import QueryConfig, get_query_config
from app.rag.query.state import QueryState

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
    retrieval_flavor: RetrievalFlavor
    strict_evidence: bool
    use_hyde: bool
    use_query_expansion: bool
    use_multi_hop: bool
    fallback_policy: FallbackPolicy
    budget: RetrievalBudget
    prompt_policy: PromptPolicy


def query_plan_node(state: QueryState, config: RunnableConfig) -> dict:
    """Resolve high-level query controls into one plan for downstream nodes."""
    cfg = get_query_config(config)
    plan = build_query_plan(
        query=state["query"],
        entity_mode=state.get("entity_mode", "none"),
        cfg=cfg,
    )
    return {"query_plan": asdict(plan)}


def build_query_plan(query: str, entity_mode: str, cfg: QueryConfig) -> QueryPlan:
    flavor = _normalize_flavor(cfg.retrieval_flavor)
    strict = bool(cfg.strict_evidence)

    if flavor == "exact":
        use_hyde = False
        use_query_expansion = False
        use_multi_hop = False
        fallback_allowed = False
        budget = RetrievalBudget(
            search_limit=8,
            hyde_limit=0,
            rrf_top_k=8,
            rerank_candidate_k=8,
            final_context_k=3,
            max_context_chars=5000,
            per_entity_min_k=3,
            reason="exact_precision",
        )
    elif flavor == "discovery":
        use_hyde = False
        use_query_expansion = False
        use_multi_hop = True
        fallback_allowed = False
        budget = RetrievalBudget(
            search_limit=cfg.search_limit,
            hyde_limit=0,
            rrf_top_k=cfg.rrf_max_results,
            rerank_candidate_k=cfg.rerank_max_top_k,
            final_context_k=cfg.rerank_max_top_k,
            max_context_chars=8000,
            per_entity_min_k=5,
            reason="discovery_current_path",
        )
    elif flavor == "recall":
        use_hyde = False
        use_query_expansion = cfg.use_query_expansion
        use_multi_hop = cfg.use_multi_hop
        fallback_allowed = not strict
        budget = RetrievalBudget(
            search_limit=20,
            hyde_limit=0,
            rrf_top_k=40,
            rerank_candidate_k=30,
            final_context_k=8,
            max_context_chars=14000,
            per_entity_min_k=8,
            reason="recall_high_coverage",
        )
    else:
        use_hyde = cfg.use_hyde
        use_query_expansion = False
        use_multi_hop = cfg.use_multi_hop
        fallback_allowed = not strict
        if entity_mode == "broad":
            budget = RetrievalBudget(
                search_limit=min(cfg.search_limit * 2, 24),
                hyde_limit=cfg.hyde_limit,
                rrf_top_k=min(cfg.rrf_max_results * 2, 32),
                rerank_candidate_k=min(cfg.rerank_max_top_k * 2, 24),
                final_context_k=min(cfg.rerank_max_top_k * 2, 8),
                max_context_chars=12000,
                per_entity_min_k=5,
                reason="balanced_broad",
            )
        else:
            budget = RetrievalBudget(
                search_limit=cfg.search_limit,
                hyde_limit=cfg.hyde_limit,
                rrf_top_k=cfg.rrf_max_results,
                rerank_candidate_k=cfg.rerank_max_top_k,
                final_context_k=cfg.rerank_max_top_k,
                max_context_chars=8000,
                per_entity_min_k=5,
                reason="balanced_current_defaults",
            )

    if entity_mode == "multi_explicit":
        budget = dataclasses.replace(budget, per_entity_min_k=8)
    budget = _clamp_budget(budget)

    fallback_policy = FallbackPolicy(
        entity_filter_to_global=fallback_allowed,
        reason="enabled_by_flavor" if fallback_allowed else "disabled_by_flavor_or_strict_evidence",
    )
    prompt_policy = PromptPolicy(
        strict_evidence=strict,
        template=_prompt_template(flavor, entity_mode),
    )

    return QueryPlan(
        retrieval_flavor=flavor,
        strict_evidence=strict,
        use_hyde=use_hyde,
        use_query_expansion=use_query_expansion,
        use_multi_hop=use_multi_hop,
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
        query=state.get("query", ""),
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


def _prompt_template(flavor: RetrievalFlavor, entity_mode: str) -> str:
    if entity_mode == "multi_explicit":
        return "multi_entity"
    if flavor == "discovery" or entity_mode == "broad":
        return "broad"
    return "default"
