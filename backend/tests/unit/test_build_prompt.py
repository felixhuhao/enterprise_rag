"""Unit tests for build_prompt: three-tier table annotation, context numbering."""

from app.rag.query.build_prompt import build_prompt_node, _build_header
from app.rag.query.config import QueryConfig


class TestBuildHeader:
    def test_text_no_annotation(self):
        r = {"file_title": "年报.pdf", "section_title": "概述", "source_type": "text", "table_tokens": 0}
        h = _build_header(r, "C1", QueryConfig())
        assert "完整表格" not in h
        assert "大型表格" not in h

    def test_small_table_annotated(self):
        r = {"file_title": "年报.pdf", "section_title": "财务", "source_type": "table_full", "table_tokens": 800, "raw_table_path": ""}
        h = _build_header(r, "C1", QueryConfig())
        assert "完整表格" in h

    def test_medium_table_has_raw_path(self):
        r = {"file_title": "年报.pdf", "section_title": "财务", "source_type": "table_row_group", "table_tokens": 4000, "raw_table_path": "/tmp/raw.md"}
        h = _build_header(r, "C1", QueryConfig())
        assert "中等表格" in h
        assert "/tmp/raw.md" in h

    def test_large_table_marks_partial(self):
        r = {"file_title": "年报.pdf", "section_title": "财务", "source_type": "table_row_group", "table_tokens": 8000, "raw_table_path": ""}
        h = _build_header(r, "C1", QueryConfig())
        assert "大型表格" in h
        assert "仅展示部分行" in h

    def test_custom_thresholds(self):
        cfg = QueryConfig(table_full_token_limit=500, table_medium_token_limit=1500)
        r = {"file_title": "t.pdf", "section_title": "s", "source_type": "table_row_group", "table_tokens": 1000, "raw_table_path": ""}
        h = _build_header(r, "C1", cfg)
        assert "中等表格" in h


class TestBuildPromptNode:
    def test_context_numbering(self):
        state = {
            "query": "毛利率",
            "search_results": [
                {"content": "毛利率 52%", "file_title": "年报.pdf", "section_title": "财务", "source_type": "text", "table_tokens": 0},
                {"content": "营收 100亿", "file_title": "年报.pdf", "section_title": "营收", "source_type": "text", "table_tokens": 0},
            ],
        }
        config = {"configurable": {"query_config": QueryConfig()}}
        result = build_prompt_node(state, config)
        assert "[C1]" in result["context_text"]
        assert "[C2]" in result["context_text"]
        assert "C1" in result["context_map"]
        assert "C2" in result["context_map"]

    def test_empty_results(self):
        state = {"query": "test", "search_results": []}
        config = {"configurable": {"query_config": QueryConfig()}}
        result = build_prompt_node(state, config)
        assert result["context_map"] == {}
        assert "test" in result["context_text"]
