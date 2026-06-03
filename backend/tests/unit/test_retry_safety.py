"""Unit tests for P1 retry safety + P1.5 delete consistency.

Tests real service-layer functions against an in-memory SQLite via monkeypatch.
"""

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.rag.chunking.chunk_keys import base_chunk_key
from app.services import document_service as svc


# ---------------------------------------------------------------------------
# In-memory fake DB
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS general_documents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id    TEXT NOT NULL UNIQUE,
    filename       TEXT NOT NULL,
    source_path    TEXT NOT NULL,
    file_type      TEXT NOT NULL,
    ingestion_mode TEXT NOT NULL DEFAULT 'text_only',
    entity_name    TEXT DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'uploaded',
    chunk_count    INTEGER DEFAULT 0,
    image_count    INTEGER DEFAULT 0,
    quality_status TEXT DEFAULT 'unavailable',
    quality_warning_count INTEGER DEFAULT 0,
    parser_version TEXT DEFAULT '',
    chunker_version TEXT DEFAULT '',
    enrichment_profile TEXT DEFAULT '',
    processed_at   TEXT DEFAULT '',
    retry_count    INTEGER DEFAULT 0,
    last_failed_stage TEXT DEFAULT '',
    cleanup_status TEXT DEFAULT '',
    error_msg      TEXT DEFAULT '',
    error_code     TEXT DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_error_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    stage       TEXT NOT NULL,
    error_code  TEXT NOT NULL,
    error_msg   TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


class _AsyncCursor:
    """Wraps sqlite3.Cursor — fetch methods return awaitables like aiosqlite."""

    def __init__(self, cursor):
        self._cursor = cursor

    async def fetchone(self):
        return self._cursor.fetchone()

    async def fetchall(self):
        return self._cursor.fetchall()

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _AwaitableCursor:
    """Supports both `await` and `async with` like aiosqlite's execute()."""

    def __init__(self, cursor):
        self._async_cursor = _AsyncCursor(cursor)

    def __await__(self):
        async def _self():
            return self._async_cursor
        return _self().__await__()

    async def __aenter__(self):
        return self._async_cursor

    async def __aexit__(self, *args):
        pass


class _FakeDb:
    """Synchronous wrapper over sqlite3.Connection that mimics aiosqlite interface."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, val):
        self._conn.row_factory = val

    def execute(self, sql, params=None):
        cursor = self._conn.execute(sql, params) if params else self._conn.execute(sql)
        return _AwaitableCursor(cursor)

    async def commit(self):
        self._conn.commit()

    async def close(self):
        pass


@pytest.fixture
def db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    now = datetime.now().isoformat()
    for doc_id, status, retry_count, cleanup_status in [
        ("doc-1", "failed", 0, ""),
        ("doc-2", "failed", 2, ""),
        ("doc-3", "failed", 3, ""),
        ("doc-4", "uploaded", 0, ""),
        ("doc-5", "parsing", 0, ""),
        ("doc-6", "embedding", 0, ""),
        ("doc-7", "completed", 0, "milvus_delete_failed"),
    ]:
        conn.execute(
            "INSERT INTO general_documents (document_id, filename, source_path, file_type, status, retry_count, cleanup_status, created_at, updated_at) VALUES (?, 'test.pdf', '/tmp/test.pdf', 'pdf', ?, ?, ?, ?, ?)",
            (doc_id, status, retry_count, cleanup_status, now, now),
        )
    conn.commit()

    fake = _FakeDb(conn)

    @asynccontextmanager
    async def _mock_get_db():
        yield fake

    monkeypatch.setattr("app.services.document_service.get_db", _mock_get_db)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Tests: update_document_status — retry_count + whitelist
# ---------------------------------------------------------------------------

class TestUpdateDocumentStatus:

    def test_rejects_unknown_field(self, db):
        with pytest.raises(ValueError, match="不允许的字段"):
            asyncio.run(svc.update_document_status("doc-1", "processing", unknown_field="x"))

    def test_updates_retry_count(self, db):
        asyncio.run(svc.update_document_status("doc-2", "processing", retry_count=3))
        row = db.execute("SELECT retry_count, status FROM general_documents WHERE document_id = 'doc-2'").fetchone()
        assert row["retry_count"] == 3
        assert row["status"] == "processing"

    def test_updates_last_failed_stage(self, db):
        asyncio.run(svc.update_document_status("doc-1", "failed", last_failed_stage="parsing", error_code="MINERU_API_ERROR"))
        row = db.execute("SELECT last_failed_stage, error_code FROM general_documents WHERE document_id = 'doc-1'").fetchone()
        assert row["last_failed_stage"] == "parsing"
        assert row["error_code"] == "MINERU_API_ERROR"

    def test_updates_quality_summary_fields(self, db):
        asyncio.run(svc.update_document_status(
            "doc-2",
            "completed",
            quality_status="warning",
            quality_warning_count=2,
            parser_version="markdown_v1",
            chunker_version="markdown_chunker_v1",
            enrichment_profile="enterprise_policy",
            processed_at="2026-06-03T10:00:00",
        ))
        row = db.execute(
            "SELECT quality_status, quality_warning_count, parser_version, chunker_version, "
            "enrichment_profile, processed_at FROM general_documents WHERE document_id = 'doc-2'"
        ).fetchone()
        assert row["quality_status"] == "warning"
        assert row["quality_warning_count"] == 2
        assert row["parser_version"] == "markdown_v1"
        assert row["chunker_version"] == "markdown_chunker_v1"
        assert row["enrichment_profile"] == "enterprise_policy"
        assert row["processed_at"] == "2026-06-03T10:00:00"

    def test_claim_document_for_processing_is_atomic(self, db):
        first = asyncio.run(svc.claim_document_for_processing("doc-4"))
        second = asyncio.run(svc.claim_document_for_processing("doc-4"))
        failed_doc = asyncio.run(svc.claim_document_for_processing("doc-1"))

        row = db.execute("SELECT status FROM general_documents WHERE document_id = 'doc-4'").fetchone()
        assert first is True
        assert second is False
        assert failed_doc is False
        assert row["status"] == "processing"


# ---------------------------------------------------------------------------
# Tests: append_error_event
# ---------------------------------------------------------------------------

class TestAppendErrorEvent:

    def test_single_event(self, db):
        asyncio.run(svc.append_error_event("doc-1", "parsing", "MINERU_API_ERROR", "parse failed"))
        rows = db.execute("SELECT * FROM document_error_events WHERE document_id = 'doc-1'").fetchall()
        assert len(rows) == 1
        assert rows[0]["stage"] == "parsing"
        assert rows[0]["error_code"] == "MINERU_API_ERROR"

    def test_multiple_events_append(self, db):
        asyncio.run(svc.append_error_event("doc-2", "parsing", "MINERU_API_ERROR", "first fail"))
        asyncio.run(svc.append_error_event("doc-2", "embedding", "EMBEDDING_ERROR", "second fail"))
        rows = db.execute("SELECT * FROM document_error_events WHERE document_id = 'doc-2' ORDER BY id").fetchall()
        assert len(rows) == 2
        assert rows[0]["stage"] == "parsing"
        assert rows[1]["stage"] == "embedding"

    def test_events_independent_per_document(self, db):
        asyncio.run(svc.append_error_event("doc-1", "chunking", "UNKNOWN_ERROR", "fail A"))
        asyncio.run(svc.append_error_event("doc-2", "saving", "MILVUS_ERROR", "fail B"))
        a = db.execute("SELECT * FROM document_error_events WHERE document_id = 'doc-1'").fetchall()
        b = db.execute("SELECT * FROM document_error_events WHERE document_id = 'doc-2'").fetchall()
        assert len(a) == 1
        assert len(b) == 1

    def test_truncates_long_msg(self, db):
        long_msg = "x" * 3000
        asyncio.run(svc.append_error_event("doc-1", "test", "ERR", long_msg))
        row = db.execute("SELECT error_msg FROM document_error_events WHERE document_id = 'doc-1'").fetchone()
        assert len(row["error_msg"]) == 2000


# ---------------------------------------------------------------------------
# Tests: mark_interrupted_documents_failed
# ---------------------------------------------------------------------------

class TestMarkInterruptedDocumentsFailed:

    def test_marks_interrupted_as_failed(self, db):
        asyncio.run(svc.mark_interrupted_documents_failed())
        for doc_id in ("doc-5", "doc-6"):
            row = db.execute("SELECT status, last_failed_stage FROM general_documents WHERE document_id = ?", (doc_id,)).fetchone()
            assert row["status"] == "failed"
            assert row["last_failed_stage"] in ("parsing", "embedding")

    def test_writes_error_events_for_interrupted(self, db):
        asyncio.run(svc.mark_interrupted_documents_failed())
        events = db.execute("SELECT document_id, stage, error_code FROM document_error_events ORDER BY id").fetchall()
        assert len(events) == 2
        stages = {e["stage"] for e in events}
        assert stages == {"parsing", "embedding"}
        assert all(e["error_code"] == "UNKNOWN_ERROR" for e in events)

    def test_does_not_affect_completed_or_failed(self, db):
        asyncio.run(svc.mark_interrupted_documents_failed())
        for doc_id in ("doc-1", "doc-2", "doc-3", "doc-4"):
            row = db.execute("SELECT status FROM general_documents WHERE document_id = ?", (doc_id,)).fetchone()
            assert row["status"] in ("failed", "uploaded")


# ---------------------------------------------------------------------------
# Tests: process_document quality summary persistence
# ---------------------------------------------------------------------------

class TestProcessDocument:

    def test_persists_quality_summary_on_completion(self, db):
        with patch("app.services.document_service.os.path.isfile", return_value=True), \
             patch("app.services.document_service._sync_process_document", return_value={
                 "chunk_count": 5,
                 "image_count": 1,
                 "quality_status": "warning",
                 "quality_warning_count": 3,
                 "parser_version": "markdown_v1",
                 "chunker_version": "markdown_chunker_v1",
                 "enrichment_profile": "enterprise_policy",
                 "processed_at": "2026-06-03T10:00:00",
             }), \
             patch("app.services.document_service._invalidate_entity_cache"):
            asyncio.run(svc.process_document("doc-4"))

        row = db.execute(
            "SELECT status, chunk_count, image_count, quality_status, quality_warning_count, "
            "parser_version, chunker_version, enrichment_profile, processed_at "
            "FROM general_documents WHERE document_id = 'doc-4'"
        ).fetchone()
        assert row["status"] == "completed"
        assert row["chunk_count"] == 5
        assert row["image_count"] == 1
        assert row["quality_status"] == "warning"
        assert row["quality_warning_count"] == 3
        assert row["parser_version"] == "markdown_v1"
        assert row["chunker_version"] == "markdown_chunker_v1"
        assert row["enrichment_profile"] == "enterprise_policy"
        assert row["processed_at"] == "2026-06-03T10:00:00"

    def test_updates_job_on_completion(self, db):
        mark_running = AsyncMock()
        update_progress = AsyncMock()
        mark_succeeded = AsyncMock()
        with patch("app.services.document_service.os.path.isfile", return_value=True), \
             patch("app.services.document_service._sync_process_document", return_value={
                 "chunk_count": 5,
                 "image_count": 1,
             }), \
             patch("app.services.document_service._invalidate_entity_cache"), \
             patch("app.services.document_service.job_service.mark_job_running", mark_running), \
             patch("app.services.document_service.job_service.update_job_progress", update_progress), \
             patch("app.services.document_service.job_service.mark_job_succeeded", mark_succeeded):
            asyncio.run(svc.process_document("doc-4", job_id="job-1"))

        row = db.execute("SELECT status FROM general_documents WHERE document_id = 'doc-4'").fetchone()
        assert row["status"] == "completed"
        mark_running.assert_awaited_once_with("job-1", message="processing")
        mark_succeeded.assert_awaited_once_with("job-1", message="Document processing completed")
        assert any(
            call.kwargs.get("message") == "completed"
            and call.kwargs.get("progress_current") == svc.DOCUMENT_JOB_TOTAL_STEPS
            for call in update_progress.await_args_list
        )

    def test_marks_job_failed_on_processing_exception(self, db):
        mark_failed = AsyncMock()
        with patch("app.services.document_service.os.path.isfile", return_value=True), \
             patch("app.services.document_service._sync_process_document", side_effect=RuntimeError("boom")), \
             patch("app.services.document_service.job_service.mark_job_running", AsyncMock()), \
             patch("app.services.document_service.job_service.update_job_progress", AsyncMock()), \
             patch("app.services.document_service.job_service.mark_job_failed", mark_failed):
            asyncio.run(svc.process_document("doc-4", job_id="job-1"))

        row = db.execute(
            "SELECT status, error_msg, last_failed_stage FROM general_documents WHERE document_id = 'doc-4'"
        ).fetchone()
        assert row["status"] == "failed"
        assert "boom" in row["error_msg"]
        assert row["last_failed_stage"] == "processing"
        mark_failed.assert_awaited_once()
        assert mark_failed.await_args.kwargs["error_code"] == "UNKNOWN_ERROR"
        assert "boom" in mark_failed.await_args.kwargs["error_detail"]

    def test_sync_status_updater_updates_document_and_job_progress(self, db):
        update_progress = AsyncMock()
        with patch("app.services.document_service.job_service.update_job_progress", update_progress):
            svc._sync_update_status("doc-4", "chunking", job_id="job-1")

        row = db.execute("SELECT status FROM general_documents WHERE document_id = 'doc-4'").fetchone()
        assert row["status"] == "chunking"
        update_progress.assert_awaited_once_with(
            "job-1",
            progress_current=4,
            progress_total=svc.DOCUMENT_JOB_TOTAL_STEPS,
            message="chunking",
        )


# ---------------------------------------------------------------------------
# Tests: delete_document — P1.5 delete consistency
# ---------------------------------------------------------------------------

class TestDeleteDocument:

    def test_fully_deleted(self, db):
        """Milvus 成功 → 返回 deleted，DB 记录消失。"""
        with patch("app.services.document_service._sync_delete_from_milvus"), \
             patch("app.services.document_service._delete_local_artifacts"), \
             patch("app.services.document_service._invalidate_entity_cache"):
            result = asyncio.run(svc.delete_document("doc-4"))
        assert result == "deleted"
        row = db.execute("SELECT * FROM general_documents WHERE document_id = 'doc-4'").fetchone()
        assert row is None

    def test_milvus_failure_returns_partial(self, db):
        """Milvus 失败 → 返回 partial，DB 保留 + cleanup_status 标记 + error event。"""
        with patch("app.services.document_service._sync_delete_from_milvus", side_effect=RuntimeError("milvus down")), \
             patch("app.services.document_service._delete_local_artifacts"), \
             patch("app.services.document_service._invalidate_entity_cache"):
            result = asyncio.run(svc.delete_document("doc-4"))
        assert result == "partial"
        # DB 记录保留
        row = db.execute("SELECT cleanup_status, status FROM general_documents WHERE document_id = 'doc-4'").fetchone()
        assert row["cleanup_status"] == "milvus_delete_failed"
        assert row["status"] == "uploaded"
        # error event 写入
        events = db.execute("SELECT * FROM document_error_events WHERE document_id = 'doc-4' AND stage = 'delete_cleanup'").fetchall()
        assert len(events) == 1
        assert events[0]["error_code"] == "MILVUS_ERROR"

    def test_not_found(self, db):
        """文档不存在 → 返回 not_found。"""
        with patch("app.services.document_service._sync_delete_from_milvus"), \
             patch("app.services.document_service._invalidate_entity_cache"):
            result = asyncio.run(svc.delete_document("nonexistent"))
        assert result == "not_found"


class TestRepairDeleteDocument:

    def test_repair_success(self, db):
        """repair 成功 → DB 记录删除。"""
        with patch("app.services.document_service._sync_delete_from_milvus"), \
             patch("app.services.document_service._delete_local_artifacts"), \
             patch("app.services.document_service._invalidate_entity_cache"):
            result = asyncio.run(svc.repair_delete_document("doc-7"))
        assert result == "deleted"
        row = db.execute("SELECT * FROM general_documents WHERE document_id = 'doc-7'").fetchone()
        assert row is None

    def test_repair_rejects_non_cleanup(self, db):
        """非 milvus_delete_failed 状态 → raise ValueError。"""
        with patch("app.services.document_service._sync_delete_from_milvus"):
            with pytest.raises(ValueError, match="不处于可修复删除状态"):
                asyncio.run(svc.repair_delete_document("doc-4"))

    def test_repair_rejects_nonexistent(self, db):
        """文档不存在 → raise ValueError。"""
        with patch("app.services.document_service._sync_delete_from_milvus"):
            with pytest.raises(ValueError, match="不处于可修复删除状态"):
                asyncio.run(svc.repair_delete_document("nonexistent"))

    def test_repair_milvus_failure_propagates(self, db):
        """Milvus 仍然失败 → 异常传播（API 层会转 503）。"""
        with patch("app.services.document_service._sync_delete_from_milvus", side_effect=RuntimeError("still down")):
            with pytest.raises(RuntimeError, match="still down"):
                asyncio.run(svc.repair_delete_document("doc-7"))
        # DB 记录保留
        row = db.execute("SELECT cleanup_status FROM general_documents WHERE document_id = 'doc-7'").fetchone()
        assert row["cleanup_status"] == "milvus_delete_failed"


class TestDocumentChunks:

    def test_milvus_chunks_are_normalized(self, db):
        """Milvus chunks 优先，解析 image_paths 并派生稳定 chunk_key。"""
        with patch("app.services.document_service._sync_query_milvus_chunks", return_value=[
            {
                "chunk_id": 123,
                "document_id": "doc-4",
                "file_title": "test.pdf",
                "entity_name": "ACME",
                "content": "hello chunk",
                "title": "Title",
                "parent_title": "Parent",
                "section_title": "Parent > Title",
                "part": 0,
                "page": 2,
                "source_type": "text",
                "table_id": "",
                "table_title": "",
                "raw_table_path": "",
                "table_tokens": None,
                "image_paths": json.dumps(["images/a.png"]),
            }
        ]):
            payload = asyncio.run(svc.get_document_chunks("doc-4"))

        assert payload["chunks_source"] == "milvus"
        assert payload["document"]["document_id"] == "doc-4"
        chunk = payload["chunks"][0]
        assert chunk["milvus_chunk_id"] == 123
        assert chunk["chunk_key"] == base_chunk_key({
            "document_id": "doc-4",
            "source_type": "text",
            "table_id": "",
            "section_title": "Parent > Title",
            "part": 0,
            "content": "hello chunk",
        })
        assert chunk["image_paths"] == ["images/a.png"]
        assert chunk["content_length"] == len("hello chunk")

    def test_falls_back_to_parsed_chunks(self, db, tmp_path, monkeypatch):
        """Milvus 无结果时读取 parsed_dir/chunks.json。"""
        parsed_dir = tmp_path / "doc-4"
        parsed_dir.mkdir()
        (parsed_dir / "chunks.json").write_text(json.dumps([
            {
                "document_id": "doc-4",
                "content": "parsed chunk",
                "source_type": "table_summary",
                "table_id": "t1",
                "part": 1,
                "image_paths": ["images/b.png"],
            }
        ], ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(svc.settings, "GENERAL_PARSED_DIR", str(tmp_path))

        with patch("app.services.document_service._sync_query_milvus_chunks", return_value=[]):
            payload = asyncio.run(svc.get_document_chunks("doc-4"))

        assert payload["chunks_source"] == "parsed_artifact"
        chunk = payload["chunks"][0]
        assert chunk["chunk_key"] == base_chunk_key({
            "document_id": "doc-4",
            "source_type": "table_summary",
            "table_id": "t1",
            "section_title": "",
            "part": 1,
            "content": "parsed chunk",
        })
        assert chunk["milvus_chunk_id"] is None
        assert chunk["content"] == "parsed chunk"

    def test_get_chunk_by_key_from_milvus(self, db):
        key = "ck_milvus"
        with patch("app.services.document_service._sync_query_milvus_chunk_by_key", return_value={
            "chunk_id": 123,
            "chunk_key": key,
            "document_id": "doc-4",
            "content": "full source",
            "source_type": "text",
            "part": 1,
            "image_paths": "[]",
        }):
            chunk = asyncio.run(svc.get_document_chunk_by_key("doc-4", key))

        assert chunk["chunk_key"] == key
        assert chunk["content"] == "full source"
        assert chunk["milvus_chunk_id"] == 123

    def test_get_chunk_by_key_falls_back_to_parsed_chunks(self, db, tmp_path, monkeypatch):
        row = {
            "document_id": "doc-4",
            "content": "parsed source",
            "source_type": "text",
            "section_title": "S",
            "part": 1,
        }
        key = base_chunk_key(row)
        parsed_dir = tmp_path / "doc-4"
        parsed_dir.mkdir()
        (parsed_dir / "chunks.json").write_text(json.dumps([row], ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(svc.settings, "GENERAL_PARSED_DIR", str(tmp_path))

        with patch("app.services.document_service._sync_query_milvus_chunk_by_key", return_value=None):
            chunk = asyncio.run(svc.get_document_chunk_by_key("doc-4", key))

        assert chunk["chunk_key"] == key
        assert chunk["content"] == "parsed source"

    def test_get_chunk_by_key_returns_none_for_missing(self, db):
        with patch("app.services.document_service._sync_query_milvus_chunk_by_key", return_value=None):
            chunk = asyncio.run(svc.get_document_chunk_by_key("doc-4", "ck_missing"))

        assert chunk is None

    def test_missing_document_returns_none(self, db):
        payload = asyncio.run(svc.get_document_chunks("missing"))
        assert payload is None
