import asyncio
import sqlite3
from datetime import datetime

from app.core import database


_SQLITE_SYNCHRONOUS_VALUES = {
    "OFF": 0,
    "NORMAL": 1,
    "FULL": 2,
    "EXTRA": 3,
}


def run(coro):
    return asyncio.run(coro)


def test_init_db_migrates_general_document_quality_summary_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    now = datetime.now().isoformat()
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE general_documents (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id    TEXT NOT NULL UNIQUE,
            filename       TEXT NOT NULL,
            source_path    TEXT NOT NULL,
            file_type      TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'uploaded',
            chunk_count    INTEGER DEFAULT 0,
            image_count    INTEGER DEFAULT 0,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO general_documents "
        "(document_id, filename, source_path, file_type, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("doc-old", "old.md", "/tmp/old.md", "md", "completed", now, now),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(database, "DB_PATH", str(db_path))

    run(database.init_db())

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(general_documents)").fetchall()}
    row = conn.execute(
        "SELECT quality_status, quality_warning_count, parser_version, chunker_version, "
        "enrichment_profile, processed_at FROM general_documents WHERE document_id = 'doc-old'"
    ).fetchone()
    conn.close()

    assert {
        "quality_status",
        "quality_warning_count",
        "parser_version",
        "chunker_version",
        "enrichment_profile",
        "processed_at",
    }.issubset(columns)
    assert row["quality_status"] == "unavailable"
    assert row["quality_warning_count"] == 0
    assert row["parser_version"] == ""
    assert row["chunker_version"] == ""
    assert row["enrichment_profile"] == ""
    assert row["processed_at"] == ""


def test_init_db_creates_jobs_table(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))

    run(database.init_db())

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    conn.close()

    assert {
        "job_id",
        "job_type",
        "status",
        "resource_type",
        "resource_id",
        "progress_current",
        "progress_total",
        "message",
        "error_code",
        "error_detail",
        "attempt_count",
        "created_by",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
    }.issubset(columns)


def test_init_db_sets_sqlite_pragmas_for_new_connections(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))

    run(database.init_db())
    status = run(database.sqlite_pragma_status())

    assert status["journal_mode"] == "wal"
    assert status["busy_timeout"] == database.SQLITE_BUSY_TIMEOUT_MS
    assert status["foreign_keys"] == 1
    assert status["synchronous"] == _SQLITE_SYNCHRONOUS_VALUES[database.SQLITE_SYNCHRONOUS]
