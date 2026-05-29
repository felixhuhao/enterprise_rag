"""Central query behavior planner."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from langgraph.graph.state import RunnableConfig

from app.rag.query.config import QueryConfig, get_query_config
from app.rag.query.state import QueryState

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
    reason: str


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
        use_multi_hop = False
        fallback_allowed = False
        budget = RetrievalBudget(
            search_limit=min(cfg.search_limit, 8),
            hyde_limit=0,
            rrf_top_k=min(cfg.rrf_max_results, 8),
            rerank_candidate_k=min(cfg.rerank_max_top_k, 8),
            final_context_k=min(cfg.rerank_max_top_k, 3),
            max_context_chars=5000,
            reason="exact_precision",
        )
    elif flavor == "discovery":
        use_hyde = False
        use_multi_hop = True
        fallback_allowed = False
        budget = RetrievalBudget(
            search_limit=cfg.search_limit,
            hyde_limit=0,
            rrf_top_k=cfg.rrf_max_results,
            rerank_candidate_k=cfg.rerank_max_top_k,
            final_context_k=cfg.rerank_max_top_k,
            max_context_chars=8000,
            reason="discovery_current_path",
        )
    else:
        use_hyde = cfg.use_hyde
        use_multi_hop = cfg.use_multi_hop
        fallback_allowed = not strict
        budget = RetrievalBudget(
            search_limit=cfg.search_limit,
            hyde_limit=cfg.hyde_limit,
            rrf_top_k=cfg.rrf_max_results,
            rerank_candidate_k=cfg.rerank_max_top_k,
            final_context_k=cfg.rerank_max_top_k,
            max_context_chars=8000,
            reason=f"{flavor}_current_defaults",
        )

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
        use_query_expansion=False,
        use_multi_hop=use_multi_hop,
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
