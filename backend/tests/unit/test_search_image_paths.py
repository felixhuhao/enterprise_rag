"""Unit tests for image_paths parsing in Milvus search results."""

import json

from app.rag.vectorstores.milvus_hits import parse_hits


def test_parse_hits_includes_image_paths_when_enabled():
    paths = ["/abs/a.jpg", "/abs/b.png"]
    rows = parse_hits([{
        "id": 123,
        "distance": 0.9,
        "entity": {
            "document_id": "doc-1",
            "source_type": "text",
            "content": "hello",
            "image_paths": json.dumps(paths, ensure_ascii=False),
        },
    }], include_image_paths=True)

    assert rows[0]["image_paths"] == paths


def test_parse_hits_omits_image_paths_by_default():
    rows = parse_hits([{
        "id": 123,
        "distance": 0.9,
        "entity": {
            "document_id": "doc-1",
            "source_type": "text",
            "content": "hello",
            "image_paths": '["/abs/a.jpg"]',
        },
    }])

    assert "image_paths" not in rows[0]
