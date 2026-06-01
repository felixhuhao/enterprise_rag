"""Unit tests for rerank_node: disabled passthrough, rerank_debug structure."""

from unittest.mock import patch

from app.rag.query.config import QueryConfig
from app.rag.query.rerank import _rerank_preview, rerank_node


def _make_results(n: int, start_score: float = 0.5) -> list[dict]:
    """构造 n 条搜索结果，score 递减。"""
    return [
        {
            "score": start_score - i * 0.05,
            "content": f"chunk content {i}",
            "file_title": f"doc{i}.pdf",
            "section_title": f"section {i}",
            "source_type": "text",
            "table_id": "",
            "table_tokens": 0,
            "raw_table_path": "",
            "document_id": f"doc-{i:04d}",
        }
        for i in range(n)
    ]


class TestRerankDisabled:
    def test_passthrough_when_disabled(self):
        results = _make_results(3)
        state = {"search_results": results, "query": "测试"}
        config = {"configurable": {"query_config": QueryConfig(use_rerank=False)}}
        out = rerank_node(state, config)
        assert out["search_results"] == results
        assert out.get("rerank_debug", []) == []

    def test_empty_results(self):
        state = {"search_results": [], "query": "测试"}
        config = {"configurable": {"query_config": QueryConfig()}}
        # need to mock _batch_rerank to avoid LLM call
        with patch("app.rag.query.rerank._batch_rerank", return_value=[]):
            out = rerank_node(state, config)
        assert out["search_results"] == []
        assert out["rerank_debug"] == []


class TestRerankDebugStructure:
    def _run_rerank(self, n: int, scores: list[float] | None = None):
        results = _make_results(n)
        state = {"search_results": results, "query": "测试"}
        cfg = QueryConfig(rerank_batch_size=20)
        config = {"configurable": {"query_config": cfg}}
        if scores is None:
            scores = [0.9 - i * 0.05 for i in range(n)]
        with patch("app.rag.query.rerank._batch_rerank", return_value=scores):
            return rerank_node(state, config)

    def test_debug_has_no_content(self):
        out = self._run_rerank(5)
        for item in out["rerank_debug"]:
            assert "content" not in item

    def test_debug_structure(self):
        out = self._run_rerank(5)
        assert len(out["rerank_debug"]) == 5
        first = out["rerank_debug"][0]
        assert first["index"] == 1
        assert "file_title" in first
        assert "section_title" in first
        assert "source_type" in first
        assert "llm_score" in first
        assert "rrf_score" in first
        assert "final_score" in first

    def test_debug_capped_at_10(self):
        out = self._run_rerank(15)
        assert len(out["rerank_debug"]) <= 10

    def test_results_have_rerank_field(self):
        out = self._run_rerank(3)
        for doc in out["search_results"]:
            assert "rerank" in doc
            assert "llm_score" in doc["rerank"]
            assert "rrf_score" in doc["rerank"]
            assert "final_score" in doc["rerank"]

    def test_scores_are_rounded(self):
        out = self._run_rerank(3)
        for item in out["rerank_debug"]:
            # 3 decimal places
            for key in ("llm_score", "rrf_score", "final_score"):
                val = item[key]
                assert val == round(val, 3)


class TestRerankBudget:
    def test_final_context_k_caps_cliff_detect_result(self):
        results = _make_results(10)
        state = {
            "search_results": results,
            "query": "测试",
            "query_plan": {
                "budget": {
                    "rerank_candidate_k": 10,
                    "final_context_k": 3,
                },
            },
        }
        config = {"configurable": {"query_config": QueryConfig(rerank_batch_size=20)}}

        with (
            patch("app.rag.query.rerank._batch_rerank", return_value=[0.9] * 10),
            patch("app.rag.query.rerank.cliff_detect", return_value=10),
        ):
            out = rerank_node(state, config)

        assert len(out["search_results"]) == 3
        assert len(out["rerank_debug"]) == 3

    def test_missing_final_context_k_falls_back_to_cliff_detect(self):
        results = _make_results(6)
        state = {
            "search_results": results,
            "query": "测试",
            "query_plan": {
                "budget": {
                    "rerank_candidate_k": 6,
                },
            },
        }
        config = {"configurable": {"query_config": QueryConfig(rerank_batch_size=20)}}

        with (
            patch("app.rag.query.rerank._batch_rerank", return_value=[0.9] * 6),
            patch("app.rag.query.rerank.cliff_detect", return_value=4),
        ):
            out = rerank_node(state, config)

        assert len(out["search_results"]) == 4


class TestRerankPreview:
    def test_table_preview_uses_longer_window(self):
        cfg = QueryConfig(content_preview_length=300)
        prefix = "x" * 450
        content = f"{prefix}\n| 8 | 夜间值班制度正式实施 | 李明 | 2026-06-01 |"

        preview = _rerank_preview(
            "李明 负责 待办事项 工作 截止日期",
            {"content": content, "source_type": "table_full"},
            cfg,
        )

        assert "夜间值班制度正式实施" in preview
        assert "李明" in preview

    def test_text_preview_keeps_configured_limit(self):
        cfg = QueryConfig(content_preview_length=300)
        content = "a" * 450

        preview = _rerank_preview("anything", {"content": content, "source_type": "text"}, cfg)

        assert len(preview) == 300
