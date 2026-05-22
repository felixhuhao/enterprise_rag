"""Unit tests for image_paths JSON parsing in search results."""

import json


def test_parse_empty_image_paths():
    """json.loads('[]') returns empty list."""
    result = json.loads("[]")
    assert result == []


def test_parse_null_image_paths():
    """json.loads(None or '[]') handles null from Milvus."""
    raw = None
    result = json.loads(raw or "[]")
    assert result == []


def test_parse_valid_image_paths():
    """json.loads parses stored image_paths list."""
    paths = ["/abs/a.jpg", "/abs/b.png"]
    stored = json.dumps(paths, ensure_ascii=False)
    result = json.loads(stored)
    assert result == paths


def test_parse_empty_string_image_paths():
    """Empty string from Milvus nullable field falls back to []."""
    raw = ""
    result = json.loads(raw or "[]")
    assert result == []
