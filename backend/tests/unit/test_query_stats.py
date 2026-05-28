"""Unit tests for QueryStatsService: save with status, aggregation, trend."""

import asyncio
import sqlite3
from contextlib import asynccontextmanager

import pytest

from app.services.query_stats_service import QueryStatsService

# ---------------------------------------------------------------------------
# In-memory fake DB (same pattern as test_retry_safety.py)
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_run_stats (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT,
    query            TEXT,
    search_mode      TEXT DEFAULT '',
    search_mode_hyde TEXT DEFAULT '',
    result_count     INTEGER DEFAULT 0,
    rerank_avg_score REAL DEFAULT 0,
    rerank_top_score REAL DEFAULT 0,
    retrieval_wall_ms INTEGER DEFAULT 0,
    first_token_ms    INTEGER DEFAULT 0,
    generate_ms       INTEGER DEFAULT 0,
    total_ms          INTEGER DEFAULT 0,
    status           TEXT DEFAULT 'success',
    error_code       TEXT DEFAULT '',
    retrieved_chunks TEXT DEFAULT '[]',
    groundedness_score REAL DEFAULT NULL,
    created_at       TEXT NOT NULL
);
"""


class _AsyncCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    async def fetchone(self):
        return self._cursor.fetchone()

    async def fetchall(self):
        return self._cursor.fetchall()

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _AwaitableCursor:
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
def svc(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)

    @asynccontextmanager
    async def _fake_get_db():
        db = _FakeDb(conn)
        try:
            yield db
        finally:
            pass

    monkeypatch.setattr("app.services.query_stats_service.get_db", _fake_get_db)
    return QueryStatsService()


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSave:
    def test_success_record(self, svc):
        run(svc.save(
            "s1", "test query", "hybrid", "hyde",
            result_count=10, rerank_avg_score=0.8, rerank_top_score=0.95,
            retrieval_wall_ms=500, first_token_ms=200, generate_ms=1000, total_ms=1500,
        ))
        stats = run(svc.get_stats())
        assert stats["total_queries"] == 1
        assert stats["success_count"] == 1
        assert stats["total_failed"] == 0

    def test_search_failed_record(self, svc):
        run(svc.save(
            "s2", "fail query", "", "",
            result_count=0, rerank_avg_score=0, rerank_top_score=0,
            status="search_failed", error_code="MILVUS_ERROR",
        ))
        stats = run(svc.get_stats())
        assert stats["total_queries"] == 1
        assert stats["success_count"] == 0
        assert stats["total_failed"] == 1
        assert stats["failure_rate"] == 1.0

    def test_client_aborted_record(self, svc):
        run(svc.save(
            "s3", "abort query", "", "",
            result_count=0, rerank_avg_score=0, rerank_top_score=0,
            status="client_aborted", error_code="CLIENT_ABORTED",
        ))
        stats = run(svc.get_stats())
        assert stats["total_queries"] == 1
        assert stats["total_failed"] == 1


class TestAggregation:
    def test_avg_only_success(self, svc):
        """AVG rerank_avg_score only counts success records."""
        run(svc.save("s1", "q1", "hybrid", "", 10, 0.8, 0.95))
        run(svc.save("s2", "q2", "", "", 0, 0.0, 0.0,
                      status="search_failed", error_code="MILVUS_ERROR"))
        run(svc.save("s3", "q3", "hybrid", "", 8, 0.6, 0.7))

        stats = run(svc.get_stats())
        assert stats["total_queries"] == 3
        assert stats["success_count"] == 2
        assert stats["total_failed"] == 1
        assert stats["failure_rate"] == round(1 / 3, 3)
        # avg rerank = (0.8 + 0.6) / 2 = 0.7
        assert stats["avg_rerank_score"] == 0.7
        # avg result count = (10 + 8) / 2 = 9.0
        assert stats["avg_result_count"] == 9.0

    def test_fallback_ratio_denominator_is_success_count(self, svc):
        """fallback_ratio uses success_count, not total_queries."""
        run(svc.save("s1", "q1", "hybrid_fallback", "", 5, 0.5, 0.6))
        run(svc.save("s2", "q2", "", "", 0, 0.0, 0.0,
                      status="search_failed", error_code="MILVUS_ERROR"))

        stats = run(svc.get_stats())
        assert stats["success_count"] == 1
        assert stats["fallback_count"] == 1
        # fallback_ratio = 1 / 1 (success_count) = 1.0
        assert stats["fallback_ratio"] == 1.0

    def test_empty_db(self, svc):
        stats = run(svc.get_stats())
        assert stats["total_queries"] == 0
        assert stats["failure_rate"] == 0
        assert stats["avg_rerank_score"] == 0
        assert stats["fallback_ratio"] == 0


class TestRecords:
    def test_records_include_status(self, svc):
        run(svc.save("s1", "q1", "hybrid", "", 10, 0.8, 0.95,
                      status="success"))
        run(svc.save("s2", "q2", "", "", 0, 0.0, 0.0,
                      status="search_failed", error_code="MILVUS_ERROR"))

        result = run(svc.get_records(page=1, page_size=10))
        assert result["total"] == 2
        records = result["records"]
        # ordered by created_at DESC
        assert records[0]["status"] == "search_failed"
        assert records[0]["error_code"] == "MILVUS_ERROR"
        assert records[1]["status"] == "success"


class TestTrend:
    def test_trend_includes_failed_count(self, svc):
        run(svc.save("s1", "q1", "hybrid", "", 10, 0.8, 0.95))
        run(svc.save("s2", "q2", "", "", 0, 0.0, 0.0,
                      status="search_failed", error_code="MILVUS_ERROR"))

        trend = run(svc.get_trend())
        assert len(trend["dates"]) >= 1
        assert trend["failed_counts"][0] == 1
        assert trend["counts"][0] == 2


class TestRetrievedChunks:
    def test_save_and_read_back(self, svc):
        chunks_json = (
            '[{"chunk_id": 123, "rank": 1, "score": 0.87, '
            '"document_id": "abc", "file_title": "年报.pdf", '
            '"entity_name": "中芯国际", "section_title": "财务", '
            '"source_type": "text", "retrieval_path": "Hybrid + Rerank", '
            '"stage": "rerank"}]'
        )
        run(svc.save(
            "s1", "test query", "hybrid", "hyde",
            result_count=1, rerank_avg_score=0.87, rerank_top_score=0.87,
            retrieved_chunks=chunks_json,
        ))
        result = run(svc.get_records(page=1, page_size=10))
        records = result["records"]
        assert records[0]["retrieved_chunks"] == chunks_json

    def test_defaults_to_empty_array(self, svc):
        run(svc.save("s1", "q", "", "", 0, 0, 0))
        result = run(svc.get_records(page=1, page_size=10))
        assert result["records"][0]["retrieved_chunks"] == "[]"
