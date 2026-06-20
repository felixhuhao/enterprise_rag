"""Unit tests for multi-hop: planner, entity discover, merge."""

import sys
from types import SimpleNamespace

from app.rag.query.control.inferred import infer_signals
from app.rag.query.multi_hop import (
    _discover_entities,
    _extract_responsible_people,
    _merge_results,
    run_multi_hop_search,
)


class TestInferredMultiHop:
    def test_broad_discovery_keyword(self):
        assert infer_signals("哪些公司提到了AI投资计划", "none", []).needs_multi_hop is True
        assert infer_signals("哪些企业涉及信息安全", "broad", []).needs_multi_hop is True
        assert infer_signals("什么公司有培训计划", "none", []).needs_multi_hop is True

    def test_responsibility_followup_keyword(self):
        assert infer_signals(
            "API v1什么时候下线？迁移指南由谁负责？这个人还负责什么工作？", "none", []
        ).needs_multi_hop is True

    def test_single_with_keyword_excluded_in_p1(self):
        """P1 不支持 seed relational query，single mode 即使有发现关键词也返回 False"""
        assert infer_signals("远景能源的竞争对手有哪些", "single", []).needs_multi_hop is False
        assert infer_signals("各自", "multi_explicit", []).needs_multi_hop is False

    def test_normal_factual_query_false(self):
        assert infer_signals("毛利率是多少", "single", []).needs_multi_hop is False
        assert infer_signals("2026年培训计划内容", "none", []).needs_multi_hop is False
        assert infer_signals("报销标准是什么", "single", []).needs_multi_hop is False

    def test_generic_keyword_false(self):
        """关键词不在 DISCOVERY_KEYWORDS 中 → False"""
        assert infer_signals("介绍一下公司情况", "none", []).needs_multi_hop is False


class TestDiscoverEntities:
    def test_discovers_from_entity_name(self):
        results = [
            {"entity_name": "星辰科技", "content": "..."},
            {"entity_name": "远景能源", "content": "..."},
        ]
        discovered = _discover_entities(results, set(), 5)
        assert discovered == ["星辰科技", "远景能源"]

    def test_excludes_seed_entities(self):
        results = [
            {"entity_name": "星辰科技", "content": "..."},
            {"entity_name": "远景能源", "content": "..."},
        ]
        discovered = _discover_entities(results, {"星辰科技"}, 5)
        assert discovered == ["远景能源"]

    def test_deduplicate(self):
        results = [
            {"entity_name": "星辰科技", "content": "..."},
            {"entity_name": "星辰科技", "content": "..."},
            {"entity_name": "远景能源", "content": "..."},
        ]
        discovered = _discover_entities(results, set(), 5)
        assert discovered == ["星辰科技", "远景能源"]

    def test_skips_empty_entity(self):
        results = [
            {"entity_name": "", "content": "..."},
            {"entity_name": "星辰科技", "content": "..."},
        ]
        discovered = _discover_entities(results, set(), 5)
        assert discovered == ["星辰科技"]

    def test_max_limit(self):
        results = [
            {"entity_name": f"entity_{i}", "content": "..."} for i in range(10)
        ]
        discovered = _discover_entities(results, set(), 3)
        assert len(discovered) == 3
        assert discovered == ["entity_0", "entity_1", "entity_2"]


def test_extract_responsible_people_from_snippets_and_tables():
    results = [
        {"content": "- 李明负责编写《API v1迁移指南》，5月15日前完成"},
        {"content": "| 序号 | 任务 | 负责人 |\n| 8 | 夜间值班制度正式实施 | 李明 |"},
    ]

    assert _extract_responsible_people(results) == ["李明"]


class TestMergeResults:
    def test_dedup_by_chunk_id(self):
        hop1 = [{"chunk_id": 1, "score": 0.9, "content": "a"}]
        hop2 = [{"chunk_id": 1, "score": 0.9, "content": "a"}]
        merged = _merge_results(hop1, hop2, 10)
        assert len(merged) == 1

    def test_dedup_by_content_when_no_chunk_id(self):
        hop1 = [{"score": 0.9, "content": "same content"}]
        hop2 = [{"score": 0.8, "content": "same content"}]
        merged = _merge_results(hop1, hop2, 10)
        assert len(merged) == 1

    def test_sorted_by_score_desc(self):
        hop1 = [{"chunk_id": 1, "score": 0.5}]
        hop2 = [{"chunk_id": 2, "score": 0.9}]
        merged = _merge_results(hop1, hop2, 10)
        assert merged[0]["score"] == 0.9
        assert merged[1]["score"] == 0.5

    def test_limit_truncates(self):
        results = [{"chunk_id": i, "score": float(i)} for i in range(20)]
        merged = _merge_results(results, [], 5)
        assert len(merged) == 5


def test_run_multi_hop_preserves_hop2_fallback_info(monkeypatch):
    from app.rag.query.config import QueryConfig

    def fake_single_search(query, entity_filter, cfg, acl_filter=None):
        return {
            "search_results": [
                {"chunk_id": 1, "entity_name": "实体A", "score": 0.9, "content": "a"}
            ],
            "search_mode": "hybrid",
            "fallback_info": {},
        }

    def fake_search_node(state, config):
        return {
            "search_results": [
                {"chunk_id": 2, "entity_name": "实体A", "score": 0.8, "content": "b"}
            ],
            "search_mode": "multi_hybrid_filtered",
            "per_entity_counts": {"实体A": 1},
            "fallback_info": {
                "used": False,
                "blocked": True,
                "type": "entity_filter_to_global",
                "reason": "entity_fallback_disabled",
                "original_filter": '(entity_name == "实体A")',
            },
        }

    monkeypatch.setitem(
        sys.modules,
        "app.rag.query.search",
        SimpleNamespace(_single_search=fake_single_search, search_node=fake_search_node),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.rag.vectorstores.general_milvus",
        SimpleNamespace(verify_embedding_fingerprint=lambda: None),
    )
    out = run_multi_hop_search(
        {"query": "哪些公司提到了信息安全培训", "entity_mode": "broad", "matched_entities": []},
        "哪些公司提到了信息安全培训",
        {"configurable": {"query_config": QueryConfig(retrieval_flavor="discovery")}},
        QueryConfig(retrieval_flavor="discovery"),
        {},
    )

    assert out["entity_mode"] == "broad"
    assert out["hop_plan"] == "discovery"
    assert out["fallback_info"]["blocked"] is True
    assert out["fallback_info"]["original_filter"] == '(entity_name == "实体A")'
