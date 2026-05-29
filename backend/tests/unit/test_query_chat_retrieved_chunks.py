"""Unit tests for query chat retrieved chunk snapshots."""

import json

from app.api.query_chat import _build_retrieved_chunks


def test_retrieved_chunks_include_chunk_key_without_full_content():
    payload = _build_retrieved_chunks([
        {
            "chunk_id": 1,
            "chunk_key": "ck_abc",
            "document_id": "doc-1",
            "file_title": "a.pdf",
            "content": "完整内容" * 100,
            "score": 0.9,
        }
    ])

    rows = json.loads(payload)

    assert rows[0]["chunk_key"] == "ck_abc"
    assert rows[0]["content_preview"]
    assert "content" not in rows[0]
