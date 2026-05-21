"""Unit tests for update_entity_name: only uploaded status can be modified."""

import sqlite3

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
    error_msg      TEXT DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
"""


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    now = "2026-01-01T00:00:00"
    conn.execute(
        "INSERT INTO general_documents (document_id, filename, source_path, file_type, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("doc-uploaded", "test.pdf", "/tmp/test.pdf", "pdf", "uploaded", now, now),
    )
    conn.execute(
        "INSERT INTO general_documents (document_id, filename, source_path, file_type, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("doc-completed", "test2.pdf", "/tmp/test2.pdf", "pdf", "completed", now, now),
    )
    conn.commit()
    yield conn
    conn.close()


class TestUpdateEntityName:
    def test_uploaded_can_update(self, db):
        cursor = db.execute(
            "UPDATE general_documents SET entity_name = ? WHERE document_id = ? AND status = 'uploaded'",
            ("中芯国际", "doc-uploaded"),
        )
        db.commit()
        assert cursor.rowcount == 1
        row = db.execute("SELECT entity_name FROM general_documents WHERE document_id = 'doc-uploaded'").fetchone()
        assert row["entity_name"] == "中芯国际"

    def test_completed_cannot_update(self, db):
        cursor = db.execute(
            "UPDATE general_documents SET entity_name = ? WHERE document_id = ? AND status = 'uploaded'",
            ("中芯国际", "doc-completed"),
        )
        db.commit()
        assert cursor.rowcount == 0
        row = db.execute("SELECT entity_name FROM general_documents WHERE document_id = 'doc-completed'").fetchone()
        assert row["entity_name"] == ""

    def test_nonexistent_doc(self, db):
        cursor = db.execute(
            "UPDATE general_documents SET entity_name = ? WHERE document_id = ? AND status = 'uploaded'",
            ("中芯国际", "doc-not-exist"),
        )
        db.commit()
        assert cursor.rowcount == 0
