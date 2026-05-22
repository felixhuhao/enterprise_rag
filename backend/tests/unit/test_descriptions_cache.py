"""Unit tests for descriptions.json cache read/write."""

import json
import os

from app.rag.parsing.image_describer import _load_cache, _save_cache


class TestCacheReadWrite:
    def test_load_returns_empty_when_no_file(self, tmp_path):
        cache = _load_cache(str(tmp_path))
        assert cache == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        data = {
            "images/foo.jpg": {
                "description": "foo描述",
                "image_path": "/abs/foo.jpg",
                "status": "ok",
            },
            "images/bar.png": {
                "description": None,
                "image_path": "/abs/bar.png",
                "status": "failed",
                "error": "timeout",
            },
        }
        _save_cache(str(tmp_path), data)
        loaded = _load_cache(str(tmp_path))
        assert loaded == data

    def test_load_handles_corrupt_json(self, tmp_path):
        cache_path = tmp_path / "descriptions.json"
        cache_path.write_text("{invalid json", encoding="utf-8")
        cache = _load_cache(str(tmp_path))
        assert cache == {}

    def test_cache_file_is_utf8(self, tmp_path):
        data = {"images/test.jpg": {"description": "中文描述", "status": "ok"}}
        _save_cache(str(tmp_path), data)
        content = (tmp_path / "descriptions.json").read_text(encoding="utf-8")
        assert "中文描述" in content
