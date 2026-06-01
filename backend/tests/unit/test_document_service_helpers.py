import asyncio
import json

from app.rag.chunking.chunk_keys import base_chunk_key
from app.services import document_chunk_query, document_cleanup


def run(coro):
    return asyncio.run(coro)


def test_get_document_chunks_payload_falls_back_to_sorted_parsed_chunks_after_milvus_error():
    def query_milvus_chunks(document_id: str) -> list[dict]:
        assert document_id == "doc-1"
        raise RuntimeError("milvus unavailable")

    def load_parsed_chunks(document_id: str) -> list[dict]:
        assert document_id == "doc-1"
        return [
            {"page": 2, "content": "second"},
            {"page": 1, "content": "first"},
        ]

    def normalize_chunk(row: dict, document_id: str, sequence_index: int) -> dict:
        return {
            "document_id": document_id,
            "content": row["content"],
            "sequence": sequence_index,
        }

    payload = run(document_chunk_query.get_document_chunks_payload(
        "doc-1",
        {"document_id": "doc-1"},
        query_milvus_chunks=query_milvus_chunks,
        load_parsed_chunks=load_parsed_chunks,
        normalize_chunk=normalize_chunk,
        sort_chunks=lambda rows: sorted(rows, key=lambda row: row["page"]),
    ))

    assert payload["chunks_source"] == "parsed_artifact"
    assert payload["chunks"] == [
        {"document_id": "doc-1", "content": "first", "sequence": 1},
        {"document_id": "doc-1", "content": "second", "sequence": 2},
    ]


def test_get_document_chunk_by_key_payload_falls_back_after_milvus_error():
    def query_milvus_chunk_by_key(document_id: str, chunk_key: str) -> dict | None:
        assert document_id == "doc-1"
        assert chunk_key == "target"
        raise RuntimeError("milvus unavailable")

    def normalize_chunk(row: dict, document_id: str, sequence_index: int) -> dict:
        return {
            "chunk_key": row["chunk_key"],
            "document_id": document_id,
            "content": row["content"],
            "sequence": sequence_index,
        }

    chunk = run(document_chunk_query.get_document_chunk_by_key_payload(
        "doc-1",
        "target",
        query_milvus_chunk_by_key=query_milvus_chunk_by_key,
        load_parsed_chunks=lambda _document_id: [
            {"chunk_key": "other", "content": "first", "page": 1},
            {"chunk_key": "target", "content": "second", "page": 2},
        ],
        normalize_chunk=normalize_chunk,
        sort_chunks=lambda rows: sorted(rows, key=lambda row: row["page"]),
    ))

    assert chunk == {
        "chunk_key": "target",
        "document_id": "doc-1",
        "content": "second",
        "sequence": 2,
    }


def test_load_parsed_chunks_filters_non_dict_rows(tmp_path, monkeypatch):
    doc_dir = tmp_path / "doc-1"
    doc_dir.mkdir()
    (doc_dir / "chunks.json").write_text(
        json.dumps([
            {"content": "valid"},
            ["not", "a", "dict"],
            "also invalid",
            {"content": "also valid"},
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(document_chunk_query.settings, "GENERAL_PARSED_DIR", str(tmp_path))

    rows = document_chunk_query.load_parsed_chunks("doc-1")

    assert rows == [{"content": "valid"}, {"content": "also valid"}]


def test_normalize_chunk_parses_metadata_lists_and_derives_stable_key():
    row = {
        "document_id": "doc-1",
        "content": "hello",
        "source_type": "table_summary",
        "table_id": "t1",
        "section_title": "Policy > Approval",
        "part": 3,
        "image_paths": json.dumps(["images/a.png"]),
        "keywords": json.dumps(["approval"]),
        "structured_tags": ["approval_rule"],
    }

    chunk = document_chunk_query.normalize_chunk(row, "doc-1", 7)

    assert chunk["chunk_key"] == base_chunk_key(row)
    assert chunk["sequence"] == 7
    assert chunk["image_paths"] == ["images/a.png"]
    assert chunk["keywords"] == ["approval"]
    assert chunk["structured_tags"] == ["approval_rule"]
    assert chunk["content_length"] == len("hello")


def test_delete_document_keeps_record_on_milvus_failure_and_records_cleanup_error():
    calls: list[tuple] = []

    async def get_document(document_id: str) -> dict | None:
        calls.append(("get", document_id))
        return {"document_id": document_id, "status": "uploaded"}

    async def update_document_status(document_id: str, status: str, **kwargs) -> None:
        calls.append(("status", document_id, status, kwargs))

    async def append_error_event(document_id: str, stage: str, error_code: str, error_msg: str) -> None:
        calls.append(("event", document_id, stage, error_code, error_msg))

    async def delete_document_record(document_id: str) -> bool:
        calls.append(("delete_record", document_id))
        return True

    def delete_from_milvus(document_id: str) -> None:
        calls.append(("milvus", document_id))
        raise RuntimeError("milvus unavailable")

    result = run(document_cleanup.delete_document(
        "doc-1",
        get_document=get_document,
        update_document_status=update_document_status,
        append_error_event=append_error_event,
        delete_document_record=delete_document_record,
        delete_from_milvus=delete_from_milvus,
        delete_local_artifacts=lambda document_id: calls.append(("local", document_id)),
        invalidate_entity_cache=lambda: calls.append(("invalidate",)),
    ))

    assert result == "partial"
    assert ("local", "doc-1") in calls
    assert ("invalidate",) in calls
    assert not any(call[0] == "delete_record" for call in calls)
    assert any(
        call[0] == "status"
        and call[3]["cleanup_status"] == "milvus_delete_failed"
        and call[3]["error_code"] == "MILVUS_ERROR"
        for call in calls
    )
    assert any(
        call[:4] == ("event", "doc-1", "delete_cleanup", "MILVUS_ERROR")
        for call in calls
    )
