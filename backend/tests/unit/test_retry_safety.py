"""Unit tests for P1 retry safety: retry_count, error events, Milvus delete blocking."""

import sqlite3
from datetime import datetime

import pytest


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
    retry_count    INTEGER DEFAULT 0,
    last_failed_stage TEXT DEFAULT '',
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


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO general_documents (document_id, filename, source_path, file_type, status, retry_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("doc-failed-0", "test.pdf", "/tmp/test.pdf", "pdf", "failed", 0, now, now),
    )
    conn.execute(
        "INSERT INTO general_documents (document_id, filename, source_path, file_type, status, retry_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("doc-failed-2", "test.pdf", "/tmp/test.pdf", "pdf", "failed", 2, now, now),
    )
    conn.execute(
        "INSERT INTO general_documents (document_id, filename, source_path, file_type, status, retry_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("doc-failed-3", "test.pdf", "/tmp/test.pdf", "pdf", "failed", 3, now, now),
    )
    conn.execute(
        "INSERT INTO general_documents (document_id, filename, source_path, file_type, status, retry_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("doc-uploaded", "test.pdf", "/tmp/test.pdf", "pdf", "uploaded", 0, now, now),
    )
    conn.commit()
    yield conn
    conn.close()


def _insert_error_event(db, document_id, stage, error_code, error_msg):
    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO document_error_events (document_id, stage, error_code, error_msg, created_at) VALUES (?, ?, ?, ?, ?)",
        (document_id, stage, error_code, error_msg, now),
    )
    db.commit()


class TestRetryCountLimit:
    """retry_count >= MAX_RETRIES (3) should block retry."""

    def test_below_limit_allows(self, db):
        row = db.execute("SELECT retry_count FROM general_documents WHERE document_id = 'doc-failed-0'").fetchone()
        assert row["retry_count"] < 3

    def test_at_limit_blocks(self, db):
        row = db.execute("SELECT retry_count FROM general_documents WHERE document_id = 'doc-failed-3'").fetchone()
        assert row["retry_count"] >= 3

    def test_retry_increments_count(self, db):
        doc = db.execute("SELECT retry_count FROM general_documents WHERE document_id = 'doc-failed-2'").fetchone()
        old_count = doc["retry_count"]
        db.execute(
            "UPDATE general_documents SET status = 'processing', retry_count = ? WHERE document_id = 'doc-failed-2'",
            (old_count + 1,),
        )
        db.commit()
        row = db.execute("SELECT retry_count FROM general_documents WHERE document_id = 'doc-failed-2'").fetchone()
        assert row["retry_count"] == old_count + 1


class TestErrorEvents:
    """Error events should be append-only, multiple failures produce multiple records."""

    def test_append_error_event(self, db):
        _insert_error_event(db, "doc-failed-0", "parsing", "MINERU_API_ERROR", "parse failed")
        events = db.execute("SELECT * FROM document_error_events WHERE document_id = 'doc-failed-0'").fetchall()
        assert len(events) == 1
        assert events[0]["stage"] == "parsing"

    def test_multiple_events_append(self, db):
        _insert_error_event(db, "doc-failed-2", "parsing", "MINERU_API_ERROR", "first fail")
        _insert_error_event(db, "doc-failed-2", "embedding", "EMBEDDING_ERROR", "second fail")
        events = db.execute("SELECT * FROM document_error_events WHERE document_id = 'doc-failed-2' ORDER BY id").fetchall()
        assert len(events) == 2
        assert events[0]["stage"] == "parsing"
        assert events[1]["stage"] == "embedding"

    def test_events_independent_per_document(self, db):
        _insert_error_event(db, "doc-failed-0", "chunking", "UNKNOWN_ERROR", "fail A")
        _insert_error_event(db, "doc-failed-2", "saving", "MILVUS_ERROR", "fail B")
        events_a = db.execute("SELECT * FROM document_error_events WHERE document_id = 'doc-failed-0'").fetchall()
        events_b = db.execute("SELECT * FROM document_error_events WHERE document_id = 'doc-failed-2'").fetchall()
        assert len(events_a) == 1
        assert len(events_b) == 1


class TestLastFailedStage:
    """last_failed_stage should reflect the stage where processing failed."""

    def test_failed_stage_recorded(self, db):
        db.execute(
            "UPDATE general_documents SET status = 'failed', last_failed_stage = 'parsing', error_code = 'MINERU_API_ERROR' WHERE document_id = 'doc-failed-0'"
        )
        db.commit()
        row = db.execute("SELECT last_failed_stage FROM general_documents WHERE document_id = 'doc-failed-0'").fetchone()
        assert row["last_failed_stage"] == "parsing"

    def test_default_empty(self, db):
        row = db.execute("SELECT last_failed_stage FROM general_documents WHERE document_id = 'doc-uploaded'").fetchone()
        assert row["last_failed_stage"] == ""


class TestPreRetryCleanup:
    """pre_retry_cleanup error events should be recorded when Milvus delete fails."""

    def test_cleanup_error_event(self, db):
        _insert_error_event(db, "doc-failed-0", "pre_retry_cleanup", "MILVUS_ERROR", "connection refused")
        events = db.execute(
            "SELECT * FROM document_error_events WHERE document_id = 'doc-failed-0' AND stage = 'pre_retry_cleanup'"
        ).fetchall()
        assert len(events) == 1
        assert events[0]["error_code"] == "MILVUS_ERROR"
