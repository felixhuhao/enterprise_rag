"""Characterization tests for current query planner behavior."""

from app.rag.query.config import QueryConfig
from app.rag.query.planner import build_query_plan

CFG = QueryConfig(search_limit=10, rrf_max_results=20, rerank_max_top_k=10, hyde_limit=10)


def _budget(plan):
    b = plan.budget
    return (
        b.search_limit,
        b.hyde_limit,
        b.rrf_top_k,
        b.rerank_candidate_k,
        b.final_context_k,
        b.max_context_chars,
        b.per_entity_min_k,
    )


def test_exact_single():
    p = build_query_plan("报销标准是什么？", "single", QueryConfig(retrieval_flavor="exact"))
    assert (p.use_hyde, p.use_query_expansion, p.use_multi_hop) == (False, False, False)
    assert p.fallback_policy.entity_filter_to_global is False
    assert _budget(p) == (8, 0, 8, 8, 3, 5000, 3)
    assert p.prompt_policy.template == "default"


def test_recall_single():
    p = build_query_plan("报销标准是什么？", "single", QueryConfig(retrieval_flavor="recall"))
    assert (p.use_hyde, p.use_query_expansion) == (False, True)
    assert _budget(p) == (20, 0, 40, 30, 8, 14000, 8)


def test_discovery_broad():
    p = build_query_plan("哪些公司提到了报销？", "broad", QueryConfig(retrieval_flavor="discovery"))
    assert p.use_multi_hop is True
    assert p.fallback_policy.entity_filter_to_global is False
    assert _budget(p) == (10, 0, 20, 10, 10, 8000, 5)
    assert p.prompt_policy.template == "broad"


def test_balanced_default_single():
    p = build_query_plan("报销标准是什么？", "single", CFG)
    assert (p.use_hyde, p.use_query_expansion, p.use_multi_hop) == (True, False, False)
    assert _budget(p) == (10, 10, 20, 10, 10, 8000, 5)
    assert p.prompt_policy.template == "default"


def test_balanced_broad_scope():
    p = build_query_plan("哪些公司提到了报销？", "broad", CFG)
    assert _budget(p) == (20, 10, 32, 20, 8, 12000, 5)
    assert p.prompt_policy.template == "broad"


def test_balanced_synthesis():
    p = build_query_plan("安全事件响应和运维故障响应有什么关联和区别？", "single", CFG)
    assert _budget(p) == (20, 10, 32, 20, 10, 10000, 5)


def test_balanced_multi_explicit_per_entity():
    p = build_query_plan("A公司和B公司的报销标准", "multi_explicit", CFG)
    assert p.budget.per_entity_min_k == 8
    assert p.prompt_policy.template == "multi_entity"
