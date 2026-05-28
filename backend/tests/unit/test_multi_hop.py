"""Unit tests for multi-hop: planner, entity discover, merge."""

from app.rag.query.multi_hop import (
    _decide_multi_hop,
    _discover_entities,
    _merge_results,
)


class TestDecideMultiHop:
    def test_broad_discovery_keyword(self):
        assert _decide_multi_hop("none", "哪些公司提到了AI投资计划") is True
        assert _decide_multi_hop("broad", "哪些企业涉及信息安全") is True
        assert _decide_multi_hop("none", "什么公司有培训计划") is True

    def test_single_with_keyword_excluded_in_p1(self):
        """P1 不支持 seed relational query，single mode 即使有发现关键词也返回 False"""
        assert _decide_multi_hop("single", "远景能源的竞争对手有哪些") is False
        assert _decide_multi_hop("multi_explicit", "各自") is False

    def test_normal_factual_query_false(self):
        assert _decide_multi_hop("single", "毛利率是多少") is False
        assert _decide_multi_hop("none", "2026年培训计划内容") is False
        assert _decide_multi_hop("single", "报销标准是什么") is False

    def test_generic_keyword_false(self):
        """关键词不在 DISCOVERY_KEYWORDS 中 → False"""
        assert _decide_multi_hop("none", "介绍一下公司情况") is False


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
