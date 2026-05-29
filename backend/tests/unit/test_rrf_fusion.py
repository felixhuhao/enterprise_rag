"""Unit tests for rrf_fusion: dedup key, fusion logic."""

from app.rag.query.rrf_fusion import _dedup_key, rrf_fusion_node
from app.rag.query.config import QueryConfig


class TestDedupKey:
    def test_chunk_id_takes_priority(self):
        doc = {"chunk_id": 123, "document_id": "abc", "source_type": "text", "table_id": "", "part": 1}
        assert _dedup_key(doc) == "123"

    def test_chunk_id_string(self):
        doc = {"chunk_id": "abc-456", "document_id": "x", "source_type": "text", "table_id": "", "part": 1}
        assert _dedup_key(doc) == "abc-456"

    def test_fallback_composite_key(self):
        doc = {"document_id": "doc1", "source_type": "text", "table_id": "", "part": 3}
        assert _dedup_key(doc) == "doc1|text||3"

    def test_fallback_with_table_id(self):
        doc = {"document_id": "doc1", "source_type": "table_summary", "table_id": "doc1_t_0001", "part": 1}
        assert _dedup_key(doc) == "doc1|table_summary|doc1_t_0001|1"

    def test_different_parts_not_merged(self):
        doc1 = {"document_id": "abc", "source_type": "text", "table_id": "", "part": 1}
        doc2 = {"document_id": "abc", "source_type": "text", "table_id": "", "part": 2}
        assert _dedup_key(doc1) != _dedup_key(doc2)


class TestRRFFusion:
    def _make_doc(self, chunk_id, content, score=0.9):
        return {
            "chunk_id": chunk_id,
            "content": content,
            "score": score,
            "document_id": "doc",
            "source_type": "text",
            "table_id": "",
            "part": 1,
        }

    def test_same_chunk_boosted(self):
        """两路都有同一个 chunk_id，得分应高于只出现一次的。"""
        results_a = [self._make_doc(1, "AAA", 0.9), self._make_doc(2, "BBB", 0.8)]
        results_b = [self._make_doc(1, "AAA", 0.85), self._make_doc(3, "CCC", 0.7)]
        state = {"search_results": results_a, "search_results_hyde": results_b}
        config = {"configurable": {"query_config": QueryConfig()}}
        result = rrf_fusion_node(state, config)
        assert len(result["search_results"]) == 3
        # chunk_id=1 应排第一（两路都有）
        assert result["search_results"][0]["chunk_id"] == 1

    def test_empty_hyde_passes_through(self):
        results_a = [self._make_doc(1, "AAA", 0.9)]
        state = {"search_results": results_a, "search_results_hyde": []}
        config = {"configurable": {"query_config": QueryConfig()}}
        result = rrf_fusion_node(state, config)
        assert len(result["search_results"]) == 1
        assert result["search_results"][0]["chunk_id"] == 1
        assert result["search_results"][0]["content"] == "AAA"

    def test_no_duplicates(self):
        """同一 chunk_id 在两路各出现一次，结果不应重复。"""
        results_a = [self._make_doc(1, "AAA", 0.9)]
        results_b = [self._make_doc(1, "AAA", 0.8)]
        state = {"search_results": results_a, "search_results_hyde": results_b}
        config = {"configurable": {"query_config": QueryConfig()}}
        result = rrf_fusion_node(state, config)
        assert len(result["search_results"]) == 1
