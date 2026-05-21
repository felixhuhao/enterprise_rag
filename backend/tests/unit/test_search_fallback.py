"""Unit tests for entity filter fallback and cliff detection."""

from app.rag.query.config import QueryConfig
from app.rag.query.scoring_utils import cliff_detect, need_fallback


class TestNeedFallback:
    def _make_results(self, scores: list[float]) -> list[dict]:
        return [{"score": s, "content": f"chunk-{i}"} for i, s in enumerate(scores)]

    def test_no_filter_never_fallback(self):
        results = self._make_results([0.1])
        cfg = QueryConfig()
        assert need_fallback(results, None, cfg) is False

    def test_no_filter_empty_string(self):
        results = self._make_results([0.1])
        cfg = QueryConfig()
        assert need_fallback(results, "", cfg) is False

    def test_count_below_min(self):
        """2 results < 3 (default min) → fallback."""
        results = self._make_results([0.9, 0.8])
        cfg = QueryConfig()
        assert need_fallback(results, 'entity_name == "测试"', cfg) is True

    def test_count_meets_min_score_ok(self):
        """3 results, max_score 0.8 >= 0.6 → no fallback."""
        results = self._make_results([0.8, 0.7, 0.6])
        cfg = QueryConfig()
        assert need_fallback(results, 'entity_name == "测试"', cfg) is False

    def test_count_ok_but_score_below_min(self):
        """3 results but max_score 0.3 < 0.6 → fallback."""
        results = self._make_results([0.3, 0.2, 0.1])
        cfg = QueryConfig()
        assert need_fallback(results, 'entity_name == "测试"', cfg) is True

    def test_custom_thresholds(self):
        """Custom min_results=5, min_score=0.8."""
        results = self._make_results([0.7, 0.6, 0.5, 0.4])
        cfg = QueryConfig(entity_filter_min_results=5, entity_filter_min_score=0.8)
        # count 4 < 5 → fallback
        assert need_fallback(results, 'entity_name == "测试"', cfg) is True

    def test_empty_results_triggers_fallback(self):
        results: list[dict] = []
        cfg = QueryConfig()
        assert need_fallback(results, 'entity_name == "测试"', cfg) is True


class TestCliffDetect:
    def _make_results(self, scores: list[float]) -> list[dict]:
        return [{"score": s} for s in scores]

    def test_cliff_truncates(self):
        """Big drop between index 2 and 3 → top_k=3."""
        results = self._make_results([0.9, 0.85, 0.8, 0.3, 0.2])
        cfg = QueryConfig(rerank_min_top_k=2, rerank_max_top_k=10, rerank_cliff_threshold=0.25)
        assert cliff_detect(results, cfg) == 3

    def test_no_cliff_returns_max(self):
        """Gentle slope → return all (up to max_top_k)."""
        results = self._make_results([0.9, 0.85, 0.8, 0.75, 0.7])
        cfg = QueryConfig(rerank_min_top_k=2, rerank_max_top_k=10, rerank_cliff_threshold=0.25)
        assert cliff_detect(results, cfg) == 5

    def test_below_min_top_k(self):
        """Only 1 result, below min_top_k=2 → return 1."""
        results = self._make_results([0.9])
        cfg = QueryConfig(rerank_min_top_k=2, rerank_max_top_k=10, rerank_cliff_threshold=0.25)
        assert cliff_detect(results, cfg) == 1

    def test_max_top_k_caps(self):
        """Results exceed max_top_k → capped."""
        results = self._make_results([0.9 + i * 0.001 for i in range(20)])
        cfg = QueryConfig(rerank_min_top_k=2, rerank_max_top_k=5, rerank_cliff_threshold=0.5)
        # Descending but within max_top_k=5 → return 5
        assert cliff_detect(results, cfg) == 5

    def test_exact_min_top_k_no_cliff(self):
        """Exactly min_top_k results → return min_top_k."""
        results = self._make_results([0.9, 0.8])
        cfg = QueryConfig(rerank_min_top_k=2, rerank_max_top_k=10, rerank_cliff_threshold=0.25)
        assert cliff_detect(results, cfg) == 2
