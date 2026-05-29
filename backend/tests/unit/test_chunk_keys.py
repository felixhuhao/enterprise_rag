"""Unit tests for stable chunk keys."""

from app.rag.chunking.chunk_keys import assign_chunk_keys, base_chunk_key


def _chunk(content: str, source_type: str = "text", part: int = 1) -> dict:
    return {
        "document_id": "doc-1",
        "source_type": source_type,
        "table_id": "t1" if source_type.startswith("table_") else "",
        "section_title": "S",
        "part": part,
        "content": content,
    }


def test_same_chunk_gets_same_base_key():
    left = _chunk("hello   world")
    right = _chunk("hello world")

    assert base_chunk_key(left) == base_chunk_key(right)
    assert base_chunk_key(left).startswith("ck_")


def test_content_change_changes_key():
    assert base_chunk_key(_chunk("hello")) != base_chunk_key(_chunk("hello changed"))


def test_all_source_types_get_chunk_key():
    chunks = [
        _chunk("text", "text"),
        _chunk("summary", "table_summary"),
        _chunk("full", "table_full"),
        _chunk("rows", "table_row_group"),
    ]

    assign_chunk_keys(chunks)

    assert {c["source_type"] for c in chunks} == {
        "text",
        "table_summary",
        "table_full",
        "table_row_group",
    }
    assert all(str(c.get("chunk_key", "")).startswith("ck_") for c in chunks)


def test_duplicate_keys_get_deterministic_suffix():
    chunks = [_chunk("same"), _chunk("same"), _chunk("same")]

    assign_chunk_keys(chunks)

    assert chunks[0]["chunk_key"].startswith("ck_")
    assert chunks[1]["chunk_key"] == f"{chunks[0]['chunk_key']}_02"
    assert chunks[2]["chunk_key"] == f"{chunks[0]['chunk_key']}_03"
