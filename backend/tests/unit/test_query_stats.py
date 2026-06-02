"""Unit tests for QueryStatsService: save with status, aggregation, trend."""

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager

import pytest

from app.rag.query.config import QueryConfig
from app.services.query_observability import (
    build_query_observability_payload,
    observability_json_columns,
)
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
    citations        TEXT DEFAULT '[]',
    retrieval_flavor TEXT DEFAULT 'balanced',
    strict_evidence  INTEGER DEFAULT 0,
    fallback_used    INTEGER DEFAULT 0,
    groundedness_score REAL DEFAULT NULL,
    endpoint         TEXT DEFAULT '',
    timings_json     TEXT DEFAULT '{}',
    settings_json    TEXT DEFAULT '{}',
    result_shape_json TEXT DEFAULT '{}',
    fallback_json    TEXT DEFAULT '{}',
    token_usage_json TEXT DEFAULT '{}',
    user_id          TEXT DEFAULT '',
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

    def test_flavor_strict_and_citations_are_saved(self, svc):
        run(svc.save(
            "s4", "recall query", "hybrid", "",
            result_count=3, rerank_avg_score=0.7, rerank_top_score=0.9,
            retrieval_flavor="recall",
            strict_evidence=True,
            citations=[{"id": "C1", "document_id": "doc-1"}],
            fallback_used=True,
        ))

        result = run(svc.get_records(page=1, page_size=10))
        record = result["records"][0]
        assert record["retrieval_flavor"] == "recall"
        assert record["strict_evidence"] == 1
        assert record["fallback_used"] == 1
        assert '"C1"' in record["citations"]

    def test_observability_payload_is_saved(self, svc):
        payload = build_query_observability_payload(
            endpoint="query_chat_stream",
            status="success",
            state={
                "confirmed_entity": "星辰科技",
                "entity_mode": "single",
                "query_plan": {
                    "retrieval_flavor": "recall",
                    "strict_evidence": True,
                    "use_hyde": False,
                    "budget": {
                        "search_limit": 20,
                        "rerank_candidate_k": 30,
                        "final_context_k": 8,
                        "reason": "recall_high_coverage",
                    },
                },
                "search_results": [
                    {"document_id": "doc-1", "file_title": "制度.md"},
                    {"document_id": "doc-2", "file_title": "FAQ.md"},
                ],
                "rerank_candidates": [{"document_id": "doc-1"}, {"document_id": "doc-2"}],
                "rerank_debug": [{"final_score": 0.9}, {"final_score": 0.7}],
                "fallback_info": {"used": False, "blocked": False, "reason": ""},
            },
            trace={"rewrite_ms": 12, "rerank_ms": 34, "retrieval_wall_ms": 100},
            gen_trace={"generate_ms": 200, "total_ms": 300},
            query_config=QueryConfig(retrieval_flavor="recall", strict_evidence=True),
            citations=[{"id": "C1", "document_id": "doc-1"}],
            token_usage={
                "model": "qwen-plus",
                "prompt_tokens": "100",
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        )

        run(svc.save(
            "s5", "observed query", "hybrid", "",
            result_count=2, rerank_avg_score=0.8, rerank_top_score=0.9,
            observability=payload,
        ))

        result = run(svc.get_records(page=1, page_size=10))
        record = result["records"][0]
        assert record["endpoint"] == "query_chat_stream"
        assert json.loads(record["timings_json"])["rerank"] == 34
        assert json.loads(record["settings_json"])["selected_entities"] == ["星辰科技"]
        assert json.loads(record["result_shape_json"])["cited_documents_count"] == 1
        assert json.loads(record["fallback_json"])["used"] is False
        assert json.loads(record["token_usage_json"])["total_tokens"] == 120


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

    def test_overall_p95_latency(self, svc):
        run(svc.save("s1", "q1", "hybrid", "", 10, 0.8, 0.9, total_ms=1000))
        run(svc.save("s2", "q2", "hybrid", "", 10, 0.8, 0.9, total_ms=2000))
        run(svc.save("s3", "q3", "", "", 0, 0.0, 0.0,
                      total_ms=10000, status="search_failed"))

        stats = run(svc.get_stats())

        assert stats["p95_ms"] == 2000

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

    def test_fallback_used_column_counts_toward_ratio(self, svc):
        run(svc.save("s1", "q1", "hybrid", "", 5, 0.5, 0.6, fallback_used=True))

        stats = run(svc.get_stats())

        assert stats["fallback_count"] == 1
        assert stats["fallback_ratio"] == 1.0

    def test_get_stats_by_flavor(self, svc):
        run(svc.save("s1", "q1", "hybrid", "", 10, 0.8, 0.9,
                      total_ms=1000, retrieval_flavor="balanced"))
        run(svc.save("s2", "q2", "hybrid", "", 8, 0.6, 0.7,
                      total_ms=2000, retrieval_flavor="balanced"))
        run(svc.save("s3", "q3", "hybrid", "", 20, 0.9, 0.95,
                      total_ms=3000, retrieval_flavor="recall", fallback_used=True))
        run(svc.save("s4", "q4", "", "", 0, 0.0, 0.0,
                      status="search_failed", retrieval_flavor="exact"))

        stats = run(svc.get_stats_by_flavor())

        assert stats["balanced"]["count"] == 2
        assert stats["balanced"]["success_rate"] == 1.0
        assert stats["balanced"]["avg_rerank"] == 0.7
        assert stats["balanced"]["avg_results"] == 9.0
        assert stats["balanced"]["p95_ms"] == 2000
        assert stats["recall"]["fallback_ratio"] == 1.0
        assert stats["exact"]["success_rate"] == 0
        assert stats["discovery"]["count"] == 0

    def test_get_stats_by_strict(self, svc):
        run(svc.save("s1", "q1", "hybrid", "", 10, 0.8, 0.9,
                      total_ms=1000, strict_evidence=False))
        run(svc.save("s2", "q2", "hybrid", "", 5, 0.6, 0.7,
                      total_ms=3000, strict_evidence=True))

        stats = run(svc.get_stats_by_strict())

        assert stats["non_strict"]["count"] == 1
        assert stats["strict"]["count"] == 1
        assert stats["strict"]["p95_ms"] == 3000


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

    def test_records_filter_by_flavor(self, svc):
        run(svc.save("s1", "q1", "hybrid", "", 10, 0.8, 0.95,
                      retrieval_flavor="balanced"))
        run(svc.save("s2", "q2", "hybrid", "", 10, 0.8, 0.95,
                      retrieval_flavor="recall"))

        result = run(svc.get_records(page=1, page_size=10, flavor="recall"))

        assert result["total"] == 1
        assert result["records"][0]["retrieval_flavor"] == "recall"

    def test_record_detail_decodes_observability_and_applies_user_filter(self, svc):
        chunks_json = '[{"chunk_id": 123, "rank": 1, "document_id": "doc-1"}]'
        payload = build_query_observability_payload(
            endpoint="query_chat_stream",
            status="success",
            state={
                "search_results": [{"document_id": "doc-1"}],
                "query_plan": {"retrieval_flavor": "balanced"},
            },
            trace={"rerank_ms": 40, "generate_ms": 200, "total_ms": 240},
            citations=[{"id": "C1", "document_id": "doc-1"}],
            token_usage={"model": "qwen-plus", "total_tokens": 120},
        )
        run(svc.save(
            "s1", "q1", "hybrid", "", 1, 0.8, 0.9,
            total_ms=240,
            retrieved_chunks=chunks_json,
            citations=[{"id": "C1", "document_id": "doc-1"}],
            user_id="u1",
            observability=payload,
        ))

        detail = run(svc.get_record_detail(1, user_id="u1"))

        assert detail["retrieved_chunks_list"][0]["chunk_id"] == 123
        assert detail["citations_list"][0]["id"] == "C1"
        assert detail["observability"]["endpoint"] == "query_chat_stream"
        assert detail["observability"]["timings_ms"]["rerank"] == 40
        assert detail["slowest_stage"] == {"key": "generate", "ms": 200}
        assert detail["total_tokens"] == 120
        assert run(svc.get_record_detail(1, user_id="u2")) is None

    def test_records_include_compact_observability_fields(self, svc):
        run(svc.save(
            "s1", "q1", "hybrid", "", 1, 0.8, 0.9,
            observability=build_query_observability_payload(
                endpoint="query_chat",
                trace={"rerank_ms": 10, "generate_ms": 30},
                token_usage={"model": "qwen-plus", "total_tokens": 42},
            ),
        ))

        record = run(svc.get_records(page=1, page_size=10))["records"][0]

        assert record["endpoint"] == "query_chat"
        assert record["timings"]["rerank"] == 10
        assert record["slowest_stage"] == {"key": "generate", "ms": 30}
        assert record["model"] == "qwen-plus"
        assert record["total_tokens"] == 42

    def test_latency_breakdown_groups_by_flavor_status_endpoint_and_stage(self, svc):
        run(svc.save(
            "s1", "q1", "hybrid", "", 1, 0.8, 0.9,
            total_ms=300,
            retrieval_flavor="balanced",
            status="success",
            endpoint="query_chat_stream",
            timings={"rerank": 100, "generate": 200},
        ))
        run(svc.save(
            "s2", "q2", "hybrid", "", 1, 0.8, 0.9,
            total_ms=700,
            retrieval_flavor="recall",
            status="success",
            endpoint="query_chat_stream",
            timings={"rerank": 70, "generate": 500},
        ))
        run(svc.save(
            "s3", "q3", "", "", 0, 0, 0,
            total_ms=900,
            retrieval_flavor="balanced",
            status="llm_failed",
            endpoint="query_chat",
            timings={"generate": 900},
        ))

        breakdown = run(svc.get_latency_breakdown())

        assert breakdown["by_flavor"]["balanced"]["count"] == 2
        assert breakdown["by_flavor"]["balanced"]["p95_ms"] == 900
        assert breakdown["by_status"]["success"]["p50_ms"] == 300
        assert breakdown["by_status"]["success"]["p95_ms"] == 700
        assert breakdown["by_endpoint"]["query_chat_stream"]["count"] == 2
        assert breakdown["stages"]["rerank"]["p50_ms"] == 70
        assert breakdown["stages"]["rerank"]["p95_ms"] == 100


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
        assert result["records"][0]["timings_json"] == "{}"


class TestObservabilityPayload:
    def test_build_payload_normalizes_trace_settings_shape_and_tokens(self):
        payload = build_query_observability_payload(
            endpoint="query_chat_stream",
            status="success",
            error_code="",
            state={
                "confirmed_entity": "星辰科技",
                "matched_entities": ["星辰科技", "远景能源"],
                "entity_mode": "multi_explicit",
                "query_plan": {
                    "retrieval_flavor": "balanced",
                    "strict_evidence": False,
                    "use_hyde": True,
                    "use_query_expansion": False,
                    "fallback_policy": {"entity_filter_to_global": True, "reason": "enabled_by_flavor"},
                    "budget": {"search_limit": 10, "rerank_candidate_k": 8, "final_context_k": 5},
                },
                "search_results": [
                    {"document_id": "doc-1", "file_title": "制度.md"},
                    {"document_id": "doc-1", "file_title": "制度.md"},
                ],
                "rerank_debug": [{"final_score": 0.6}, {"final_score": 0.4}],
                "context_map": {"C1": {}, "C2": {}},
                "fallback_info": {"used": True, "blocked": False, "reason": "low_score"},
            },
            trace={"rewrite_ms": 1.4, "unknown": 99, "build_prompt_ms": 5},
            gen_trace={"first_token_ms": 20, "generate_ms": 50, "total_ms": 70},
            query_config=QueryConfig(use_hyde=True, use_rerank=True),
            citations=[{"id": "C1", "document_id": "doc-1"}],
            token_usage={"model_name": "qwen-plus", "prompt_tokens": 10, "completion_tokens": 5},
        )

        assert payload["timings_ms"] == {
            "rewrite": 1,
            "prompt_build": 5,
            "first_token": 20,
            "generate": 50,
            "total": 70,
        }
        assert payload["resolved_settings"]["selected_entities"] == ["星辰科技", "远景能源"]
        assert payload["resolved_settings"]["rerank_candidate_k"] == 8
        assert payload["result_shape"]["final_context_chunks_count"] == 2
        assert payload["result_shape"]["retrieved_documents_count"] == 1
        assert payload["result_shape"]["avg_rerank_score"] == 0.5
        assert payload["result_shape"]["empty_result_reason"] == ""
        assert payload["fallback_info"]["reason"] == "low_score"
        assert payload["token_usage"]["available"] is True
        assert payload["token_usage"]["model"] == "qwen-plus"
        assert payload["token_usage"]["total_tokens"] is None

    def test_empty_rerank_candidates_key_does_not_fallback_to_debug_count(self):
        payload = build_query_observability_payload(
            state={
                "search_results": [],
                "rerank_candidates": [],
                "rerank_debug": [{"final_score": 0.8}],
                "search_mode": "empty",
            },
        )

        assert payload["result_shape"]["retrieved_chunks_count"] == 0
        assert payload["result_shape"]["rerank_candidates_count"] == 0
        assert payload["result_shape"]["empty_result_reason"] == "empty"

    def test_observability_json_columns_defaults_to_empty_objects(self):
        columns = observability_json_columns(None)

        assert columns == {
            "endpoint": "",
            "timings_json": "{}",
            "settings_json": "{}",
            "result_shape_json": "{}",
            "fallback_json": "{}",
            "token_usage_json": "{}",
        }

    def test_token_usage_with_model_only_is_explicitly_unavailable(self):
        payload = build_query_observability_payload(
            token_usage={"model": "qwen-plus"},
        )

        assert payload["token_usage"] == {
            "available": False,
            "model": "qwen-plus",
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }
