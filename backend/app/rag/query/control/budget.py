"""Budget profile table reproducing current planner branches."""

from __future__ import annotations

import dataclasses

from app.rag.query.config import QueryConfig
from app.rag.query.planner import RetrievalBudget, _clamp_budget


def resolve_budget_profile(
    breadth: str,
    entity_scope: str,
    needs_synthesis: bool,
    cfg: QueryConfig,
) -> RetrievalBudget:
    """Return the exact current budget profile for breadth, scope, and synthesis."""
    if breadth == "precise":
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
    elif breadth == "broad":
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
    elif breadth == "discovery":
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
    elif entity_scope == "broad":
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
    elif needs_synthesis:
        budget = RetrievalBudget(
            search_limit=min(max(cfg.search_limit * 2, 20), 24),
            hyde_limit=cfg.hyde_limit,
            rrf_top_k=min(max(cfg.rrf_max_results * 2, 32), 32),
            rerank_candidate_k=min(max(cfg.rerank_max_top_k * 2, 20), 24),
            final_context_k=cfg.rerank_max_top_k,
            max_context_chars=10000,
            per_entity_min_k=5,
            reason="balanced_synthesis",
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

    if entity_scope == "multi":
        budget = dataclasses.replace(budget, per_entity_min_k=8)
    return _clamp_budget(budget)

