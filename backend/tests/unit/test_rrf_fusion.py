"""Unit tests for RRF dedup and fusion logic."""

from app.rag.query.config import QueryConfig
from app.rag.query.rrf_fusion import _dedup_key, rrf_fusion_node


class TestDedupKey:
    def test_chunk_key_takes_priority(self):
        doc = {
            "chunk_key": "ck_abc",
            "chunk_id": 123,
            "document_id": "abc",
            "source_type": "text",
            "table_id": "",
            "part": 1,
        }
        assert _dedup_key(doc) == "ck_abc"

    def test_chunk_id_fallback(self):
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
        results_a = [self._make_doc(1, "AAA", 0.9), self._make_doc(2, "BBB", 0.8)]
        results_b = [self._make_doc(1, "AAA", 0.85), self._make_doc(3, "CCC", 0.7)]
        state = {"query": "test query", "search_results": results_a, "search_results_hyde": results_b}
        config = {"configurable": {"query_config": QueryConfig()}}
        result = rrf_fusion_node(state, config)
        assert len(result["search_results"]) == 3
        assert result["search_results"][0]["chunk_id"] == 1

    def test_empty_hyde_passes_through(self):
        results_a = [self._make_doc(1, "AAA", 0.9)]
        state = {"query": "test query", "search_results": results_a, "search_results_hyde": []}
        config = {"configurable": {"query_config": QueryConfig()}}
        result = rrf_fusion_node(state, config)
        assert len(result["search_results"]) == 1
        assert result["search_results"][0]["chunk_id"] == 1
        assert result["search_results"][0]["content"] == "AAA"

    def test_no_duplicates(self):
        results_a = [self._make_doc(1, "AAA", 0.9)]
        results_b = [self._make_doc(1, "AAA", 0.8)]
        state = {"query": "test query", "search_results": results_a, "search_results_hyde": results_b}
        config = {"configurable": {"query_config": QueryConfig()}}
        result = rrf_fusion_node(state, config)
        assert len(result["search_results"]) == 1

    def test_n_way_expanded_results_are_fused(self):
        results_a = [self._make_doc(1, "AAA", 0.9), self._make_doc(2, "BBB", 0.8)]
        results_b = [self._make_doc(3, "CCC", 0.7)]
        expanded = [
            [self._make_doc(2, "BBB", 0.75), self._make_doc(4, "DDD", 0.6)],
            [self._make_doc(5, "EEE", 0.5)],
        ]
        state = {
            "query": "test query",
            "search_results": results_a,
            "search_mode": "hybrid",
            "search_results_hyde": results_b,
            "search_mode_hyde": "hyde",
            "search_results_expanded": expanded,
            "search_modes_expanded": ["hybrid", "hybrid_filtered_fallback_unfiltered"],
        }
        config = {"configurable": {"query_config": QueryConfig()}}

        result = rrf_fusion_node(state, config)

        ids = [row["chunk_id"] for row in result["search_results"]]
        assert set(ids) == {1, 2, 3, 4, 5}
        boosted = next(row for row in result["search_results"] if row["chunk_id"] == 2)
        assert "hybrid" in boosted["retrieval_paths"]
        assert "expanded_1" in boosted["retrieval_paths"]
        fallback = next(row for row in result["search_results"] if row["chunk_id"] == 5)
        assert fallback["retrieval_paths"] == ["expanded_2_fallback"]

    def test_all_empty_returns_empty(self):
        state = {"query": "test query", "search_results": [], "search_results_hyde": [], "search_results_expanded": [[]]}
        config = {"configurable": {"query_config": QueryConfig()}}
        result = rrf_fusion_node(state, config)
        assert result["search_results"] == []
