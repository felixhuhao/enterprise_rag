"""Unit tests for Milvus chunk_key schema compatibility."""

from app.rag.vectorstores import general_milvus as gm


def test_available_output_fields_omits_chunk_key_for_old_schema(monkeypatch):
    monkeypatch.setattr(gm.client, "has_collection", lambda collection_name: True)
    monkeypatch.setattr(gm.client, "describe_collection", lambda collection_name: {
        "fields": [{"name": "chunk_id"}, {"name": "content"}],
    })
    monkeypatch.setattr(gm, "_FIELD_NAMES_CACHE", None)

    fields = gm.available_output_fields(["chunk_id", "chunk_key", "content"])

    assert fields == ["chunk_id", "content"]


def test_to_milvus_row_can_omit_chunk_key():
    row = gm._to_milvus_row(
        {"content": "x", "dense": [0.1], "chunk_key": "ck_abc"},
        include_chunk_key=False,
    )

    assert "chunk_key" not in row


def test_query_chunk_by_key_skips_old_schema(monkeypatch):
    called = False

    def fake_query(**kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(gm.client, "has_collection", lambda collection_name: True)
    monkeypatch.setattr(gm.client, "describe_collection", lambda collection_name: {
        "fields": [{"name": "chunk_id"}, {"name": "content"}],
    })
    monkeypatch.setattr(gm.client, "query", fake_query)
    monkeypatch.setattr(gm, "_FIELD_NAMES_CACHE", None)

    assert gm.query_chunk_by_key("doc-1", "ck_missing") is None
    assert called is False
