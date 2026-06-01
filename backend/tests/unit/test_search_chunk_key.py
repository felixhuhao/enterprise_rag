"""Unit tests for derived chunk_key on search results."""

from app.rag.chunking.chunk_keys import base_chunk_key
from app.rag.vectorstores.milvus_hits import parse_hits


def test_parse_hits_derives_chunk_key_when_old_schema_has_none():
    entity = {
        "document_id": "doc-1",
        "source_type": "text",
        "table_id": "",
        "section_title": "S",
        "part": 1,
        "content": "hello world",
    }

    rows = parse_hits([{"id": 123, "distance": 0.9, "entity": entity}])

    assert rows[0]["chunk_key"] == base_chunk_key(entity)


def test_parse_hits_preserves_milvus_chunk_key():
    entity = {
        "chunk_key": "ck_existing",
        "document_id": "doc-1",
        "source_type": "text",
        "content": "hello world",
    }

    rows = parse_hits([{"id": 123, "distance": 0.9, "entity": entity}])

    assert rows[0]["chunk_key"] == "ck_existing"


def test_parse_hits_decodes_enrichment_metadata():
    entity = {
        "chunk_key": "ck_existing",
        "document_id": "doc-1",
        "source_type": "text",
        "content": "hello world",
        "keywords": '["VP审批"]',
        "structured_tags": '["amount_threshold", "approval_rule"]',
    }

    rows = parse_hits([{"id": 123, "distance": 0.9, "entity": entity}])

    assert rows[0]["keywords"] == ["VP审批"]
    assert rows[0]["structured_tags"] == ["amount_threshold", "approval_rule"]
