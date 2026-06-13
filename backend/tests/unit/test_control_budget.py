from app.rag.query.config import QueryConfig
from app.rag.query.control.budget import resolve_budget_profile

CFG = QueryConfig(search_limit=10, rrf_max_results=20, rerank_max_top_k=10, hyde_limit=10)


def _t(b):
    return (
        b.search_limit,
        b.hyde_limit,
        b.rrf_top_k,
        b.rerank_candidate_k,
        b.final_context_k,
        b.max_context_chars,
        b.per_entity_min_k,
    )


def test_precise():
    assert _t(resolve_budget_profile("precise", "single", False, CFG)) == (8, 0, 8, 8, 3, 5000, 3)


def test_broad():
    assert _t(resolve_budget_profile("broad", "single", False, CFG)) == (20, 0, 40, 30, 8, 14000, 8)


def test_balanced_discovery():
    budget = resolve_budget_profile("balanced", "none", False, CFG, needs_discovery=True)

    assert _t(budget) == (20, 10, 32, 20, 8, 12000, 5)
    assert budget.reason == "balanced_discovery"


def test_balanced_default():
    assert _t(resolve_budget_profile("balanced", "single", False, CFG)) == (10, 10, 20, 10, 10, 8000, 5)


def test_balanced_broad_scope():
    assert _t(resolve_budget_profile("balanced", "broad", False, CFG)) == (20, 10, 32, 20, 8, 12000, 5)


def test_balanced_synthesis():
    assert _t(resolve_budget_profile("balanced", "single", True, CFG)) == (20, 10, 32, 20, 10, 10000, 5)


def test_multi_entity_synthesis_precedes_discovery_budget():
    budget = resolve_budget_profile("balanced", "multi", True, CFG, needs_discovery=True)

    assert budget.reason == "balanced_synthesis"
    assert _t(budget) == (20, 10, 32, 20, 10, 10000, 8)


def test_multi_scope_modifier_sets_per_entity_8():
    assert resolve_budget_profile("balanced", "multi", False, CFG).per_entity_min_k == 8
    assert resolve_budget_profile("precise", "multi", False, CFG).per_entity_min_k == 8


def test_reason_strings_preserved():
    assert resolve_budget_profile("precise", "single", False, CFG).reason == "exact_precision"
    assert resolve_budget_profile("balanced", "single", True, CFG).reason == "balanced_synthesis"
    assert resolve_budget_profile("balanced", "broad", False, CFG).reason == "balanced_broad"
    assert (
        resolve_budget_profile("balanced", "none", False, CFG, needs_discovery=True).reason
        == "balanced_discovery"
    )
