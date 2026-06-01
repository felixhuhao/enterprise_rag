"""Unit tests for Milvus chunk_key schema compatibility."""

from app.rag.vectorstores import general_milvus as gm


def test_chunk_output_fields_do_not_include_search_text():
    assert "search_text" not in gm.CHUNK_OUTPUT_FIELDS
    assert "search_text" in gm.SCHEMA_FIELD_NAMES


def test_available_output_fields_omits_chunk_key_for_old_schema(monkeypatch):
    monkeypatch.setattr(gm.client, "has_collection", lambda collection_name: True)
    monkeypatch.setattr(gm.client, "describe_collection", lambda collection_name: {
        "fields": [{"name": "chunk_id"}, {"name": "content"}],
    })
    monkeypatch.setattr(gm, "_FIELD_NAMES_CACHE", None)

    fields = gm.available_output_fields(["chunk_id", "chunk_key", "content"])

    assert fields == ["chunk_id", "content"]


def test_available_output_fields_omits_enrichment_for_old_schema(monkeypatch):
    monkeypatch.setattr(gm.client, "has_collection", lambda collection_name: True)
    monkeypatch.setattr(gm.client, "describe_collection", lambda collection_name: {
        "fields": [{"name": "chunk_id"}, {"name": "content"}],
    })
    monkeypatch.setattr(gm, "_FIELD_NAMES_CACHE", None)

    fields = gm.available_output_fields([
        "chunk_id",
        "content",
        "search_text",
        "keywords",
        "structured_tags",
    ])

    assert fields == ["chunk_id", "content"]


def test_to_milvus_row_can_omit_chunk_key():
    row = gm._to_milvus_row(
        {"content": "x", "dense": [0.1], "chunk_key": "ck_abc"},
        include_chunk_key=False,
    )

    assert "chunk_key" not in row


def test_to_milvus_row_writes_enrichment_fields():
    row = gm._to_milvus_row(
        {
            "content": "source",
            "search_text": "source 金额审批阈值",
            "keywords": ["VP审批"],
            "structured_tags": ["amount_threshold", "approval_rule"],
            "dense": [0.1],
            "chunk_key": "ck_abc",
        }
    )

    assert row["search_text"] == "source 金额审批阈值"
    assert row["keywords"] == '["VP审批"]'
    assert row["structured_tags"] == '["amount_threshold", "approval_rule"]'


def test_to_milvus_row_can_omit_enrichment_for_old_schema():
    row = gm._to_milvus_row(
        {
            "content": "source",
            "search_text": "source 金额审批阈值",
            "keywords": ["VP审批"],
            "structured_tags": ["amount_threshold"],
            "dense": [0.1],
        },
        include_enrichment=False,
    )

    assert "search_text" not in row
    assert "keywords" not in row
    assert "structured_tags" not in row


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


def test_document_id_filters_are_escaped(monkeypatch):
    filters: list[str] = []

    def fake_delete(**kwargs):
        filters.append(kwargs["filter"])
        return {"delete_count": 1}

    def fake_query(**kwargs):
        filters.append(kwargs["filter"])
        return []

    monkeypatch.setattr(gm.client, "has_collection", lambda collection_name: True)
    monkeypatch.setattr(gm.client, "delete", fake_delete)
    monkeypatch.setattr(gm.client, "query", fake_query)
    monkeypatch.setattr(gm.client, "flush", lambda collection_name: None)
    monkeypatch.setattr(gm, "available_output_fields", lambda fields: fields)

    gm.delete_by_document_id('doc"1\\x')
    gm.query_chunks_by_document_id('doc"1\\x')

    assert filters == [
        'document_id == "doc\\"1\\\\x"',
        'document_id == "doc\\"1\\\\x"',
    ]
