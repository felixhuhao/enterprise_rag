"""Unit tests for entity_name priority in ingestion graph entry node."""

from unittest.mock import patch

import pytest

from app.rag.query.config import QueryConfig
from app.rag.ingestion.graph import entry


def _state(**overrides) -> dict:
    base = {
        "document_id": "test-doc",
        "filename": "兴证国际_2024年报.pdf",
        "file_type": "pdf",
        "source_path": "/tmp/test.pdf",
    }
    base.update(overrides)
    return base


def _config():
    return {"configurable": {}}


class TestEntityNamePriority:
    @pytest.fixture(autouse=True)
    def _patch_parsed_dir(self, tmp_path):
        """将 GENERAL_PARSED_DIR 指向临时目录，避免污染真实 data。"""
        with patch("app.rag.ingestion.graph.settings.GENERAL_PARSED_DIR", str(tmp_path)):
            yield

    def test_user_provided_takes_priority(self):
        """用户指定 entity_name > 文件名提取。"""
        state = _state(entity_name="中芯国际")
        config = _config()
        with patch("app.rag.ingestion.graph.extract_entity_name", return_value="兴证国际"):
            result = entry(state, config)
        assert result["entity_name"] == "中芯国际"

    def test_fallback_to_filename_extraction(self):
        """用户未指定时从文件名提取。"""
        state = _state()  # 无 entity_name
        config = _config()
        with patch("app.rag.ingestion.graph.extract_entity_name", return_value="兴证国际"):
            result = entry(state, config)
        assert result["entity_name"] == "兴证国际"

    def test_empty_string_falls_to_extraction(self):
        """用户传空字符串，等价于未指定。"""
        state = _state(entity_name="")
        config = _config()
        with patch("app.rag.ingestion.graph.extract_entity_name", return_value="兴证国际"):
            result = entry(state, config)
        assert result["entity_name"] == "兴证国际"

    def test_both_empty(self):
        """用户未指定 + 文件名提取也为空。"""
        state = _state()
        config = _config()
        with patch("app.rag.ingestion.graph.extract_entity_name", return_value=""):
            result = entry(state, config)
        assert result["entity_name"] == ""
