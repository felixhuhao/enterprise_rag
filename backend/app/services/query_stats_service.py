"""Query run statistics persistent storage and aggregations."""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from app.core.database import get_db
from app.rag.query.config import RETRIEVAL_FLAVORS, normalize_retrieval_flavor
from app.services.query_observability import json_dumps, observability_json_columns

FLAVORS = RETRIEVAL_FLAVORS
LATENCY_GROUP_FIELDS = {"retrieval_flavor", "status", "endpoint"}


class QueryStatsService:
    """Read/write service for online query statistics."""

    async def save(
        self,
        session_id: str,
        query: str,
        search_mode: str,
        search_mode_hyde: str,
        result_count: int,
        rerank_avg_score: float,
        rerank_top_score: float,
        retrieval_wall_ms: int = 0,
        first_token_ms: int = 0,
        generate_ms: int = 0,
        total_ms: int = 0,
        status: str = "success",
        error_code: str = "",
        retrieved_chunks: str = "[]",
        groundedness_score: float | None = None,
        user_id: str = "",
        retrieval_flavor: str = "balanced",
        strict_evidence: bool = False,
        citations: list[dict] | str | None = None,
        fallback_used: bool = False,
        observability: dict[str, Any] | None = None,
        endpoint: str = "",
        timings: dict[str, Any] | str | None = None,
        resolved_settings: dict[str, Any] | str | None = None,
        result_shape: dict[str, Any] | str | None = None,
        fallback_details: dict[str, Any] | str | None = None,
        token_usage: dict[str, Any] | str | None = None,
    ):
        """Save one query run."""
        now = datetime.now().isoformat()
        flavor = normalize_retrieval_flavor(retrieval_flavor)
        citations_json = _json_text(citations)
        obs_cols = observability_json_columns(observability)
        if endpoint:
            obs_cols["endpoint"] = endpoint
        if timings is not None:
            obs_cols["timings_json"] = _json_object_text(timings)
        if resolved_settings is not None:
            obs_cols["settings_json"] = _json_object_text(resolved_settings)
        if result_shape is not None:
            obs_cols["result_shape_json"] = _json_object_text(result_shape)
        if fallback_details is not None:
            obs_cols["fallback_json"] = _json_object_text(fallback_details)
        if token_usage is not None:
            obs_cols["token_usage_json"] = _json_object_text(token_usage)
        async with get_db() as db:
            await db.execute(
                """INSERT INTO query_run_stats
                   (session_id, query, search_mode, search_mode_hyde,
                    result_count, rerank_avg_score, rerank_top_score,
                    retrieval_wall_ms, first_token_ms, generate_ms, total_ms,
                    status, error_code, retrieved_chunks, citations,
                    retrieval_flavor, strict_evidence, fallback_used,
                    groundedness_score, endpoint, timings_json, settings_json,
                    result_shape_json, fallback_json, token_usage_json,
                    user_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    query[:500],
                    search_mode,
                    search_mode_hyde,
                    result_count,
                    rerank_avg_score,
                    rerank_top_score,
                    retrieval_wall_ms,
                    first_token_ms,
                    generate_ms,
                    total_ms,
                    status,
                    error_code,
                    retrieved_chunks,
                    citations_json,
                    flavor,
                    1 if strict_evidence else 0,
                    1 if fallback_used else 0,
                    groundedness_score,
                    obs_cols["endpoint"],
                    obs_cols["timings_json"],
                    obs_cols["settings_json"],
                    obs_cols["result_shape_json"],
                    obs_cols["fallback_json"],
                    obs_cols["token_usage_json"],
                    user_id,
                    now,
                ),
            )
            await db.commit()

    async def get_stats(self, user_id: str | None = None) -> dict:
        """Aggregate overall query stats. user_id=None means all users."""
        where, params = _where(user_id=user_id)
        async with get_db() as db:
            sql = (
                "SELECT COUNT(*) as total_queries, "
                "COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) as success_count, "
                "COALESCE(AVG(CASE WHEN status = 'success' THEN rerank_avg_score END), 0) as avg_rerank, "
                "COALESCE(AVG(CASE WHEN status = 'success' THEN result_count END), 0) as avg_result_count, "
                "COALESCE(SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END), 0) as total_failed, "
                "COALESCE(SUM(CASE WHEN status = 'success' AND (fallback_used = 1 "
                "  OR search_mode LIKE '%fallback%' OR search_mode_hyde LIKE '%fallback%') "
                "  THEN 1 ELSE 0 END), 0) as fallback_count, "
                "AVG(CASE WHEN status = 'success' AND groundedness_score IS NOT NULL "
                "  THEN groundedness_score END) as avg_groundedness_score, "
                "COALESCE(SUM(CASE WHEN status = 'success' AND groundedness_score IS NOT NULL "
                "  AND groundedness_score < 0.7 THEN 1 ELSE 0 END), 0) as low_groundedness_count "
                f"FROM query_run_stats {where}"
            )
            async with db.execute(sql, params) as cursor:
                row = dict(await cursor.fetchone())

            p95_where, p95_params = _where(user_id=user_id, extra="status = 'success' AND total_ms > 0")
            async with db.execute(
                f"SELECT total_ms FROM query_run_stats {p95_where} ORDER BY total_ms ASC",
                p95_params,
            ) as cursor:
                p95_rows = await cursor.fetchall()

        total = row["total_queries"] or 0
        success_count = row["success_count"] or 0
        total_failed = row["total_failed"] or 0
        fallback_count = row["fallback_count"] or 0
        return {
            "total_queries": total,
            "success_count": success_count,
            "total_failed": total_failed,
            "failure_rate": round(total_failed / total, 3) if total else 0,
            "avg_rerank_score": round(row["avg_rerank"], 3),
            "avg_result_count": round(row["avg_result_count"], 1),
            "p95_ms": _p95([int(r["total_ms"] or 0) for r in p95_rows]),
            "fallback_count": fallback_count,
            "fallback_ratio": round(fallback_count / success_count, 3) if success_count else 0,
            "avg_groundedness_score": round(row["avg_groundedness_score"], 3) if row["avg_groundedness_score"] is not None else None,
            "low_groundedness_count": row["low_groundedness_count"] or 0,
        }

    async def get_stats_by_flavor(self, user_id: str | None = None) -> dict:
        """Aggregate online stats by retrieval_flavor."""
        rows = await self._grouped_stats("retrieval_flavor", user_id=user_id)
        p95 = await self._grouped_p95("retrieval_flavor", user_id=user_id)
        return {
            flavor: _metric_row(rows.get(flavor), p95.get(flavor, 0))
            for flavor in FLAVORS
        }

    async def get_stats_by_strict(self, user_id: str | None = None) -> dict:
        """Aggregate online stats by strict_evidence."""
        rows = await self._grouped_stats("strict_evidence", user_id=user_id)
        p95 = await self._grouped_p95("strict_evidence", user_id=user_id)
        return {
            "non_strict": _metric_row(rows.get(0), p95.get(0, 0)),
            "strict": _metric_row(rows.get(1), p95.get(1, 0)),
        }

    async def _grouped_stats(self, field: str, user_id: str | None = None) -> dict[Any, dict]:
        if field not in {"retrieval_flavor", "strict_evidence"}:
            raise ValueError(f"Unsupported stats group field: {field}")
        where, params = _where(user_id=user_id)
        async with get_db() as db:
            async with db.execute(
                f"""SELECT {field} as group_key,
                          COUNT(*) as count,
                          COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) as success_count,
                          COALESCE(SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END), 0) as failed_count,
                          COALESCE(AVG(CASE WHEN status = 'success' THEN rerank_avg_score END), 0) as avg_rerank,
                          COALESCE(AVG(CASE WHEN status = 'success' THEN result_count END), 0) as avg_results,
                          COALESCE(SUM(CASE WHEN status = 'success' AND (fallback_used = 1
                            OR search_mode LIKE '%fallback%' OR search_mode_hyde LIKE '%fallback%')
                            THEN 1 ELSE 0 END), 0) as fallback_count
                   FROM query_run_stats {where}
                   GROUP BY {field}""",
                params,
            ) as cursor:
                rows = await cursor.fetchall()
        out: dict[Any, dict] = {}
        for row in rows:
            key = row["group_key"]
            if field == "strict_evidence":
                key = int(key or 0)
            out[key] = dict(row)
        return out

    async def _grouped_p95(self, field: str, user_id: str | None = None) -> dict[Any, int]:
        if field not in {"retrieval_flavor", "strict_evidence"}:
            raise ValueError(f"Unsupported stats group field: {field}")
        where, params = _where(user_id=user_id, extra="status = 'success' AND total_ms > 0")
        async with get_db() as db:
            async with db.execute(
                f"""SELECT {field} as group_key, total_ms
                   FROM query_run_stats {where}
                   ORDER BY {field}, total_ms ASC""",
                params,
            ) as cursor:
                rows = await cursor.fetchall()

        grouped: dict[Any, list[int]] = {}
        for row in rows:
            key = row["group_key"]
            if field == "strict_evidence":
                key = int(key or 0)
            grouped.setdefault(key, []).append(int(row["total_ms"] or 0))
        return {key: _p95(values) for key, values in grouped.items()}

    async def get_trend(self, days: int = 30, user_id: str | None = None) -> dict:
        """Daily trend. user_id=None means all users."""
        where, params = _where(user_id=user_id)
        async with get_db() as db:
            async with db.execute(
                f"""SELECT DATE(created_at) as date,
                          AVG(CASE WHEN status = 'success' THEN rerank_avg_score END) as avg_rerank,
                          AVG(CASE WHEN status = 'success' THEN result_count END) as avg_result_count,
                          COUNT(*) as count,
                          SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failed_count
                   FROM query_run_stats {where}
                   GROUP BY DATE(created_at)
                   ORDER BY date DESC
                   LIMIT ?""",
                (*params, days),
            ) as cursor:
                rows = await cursor.fetchall()
        return {
            "dates": [row["date"] for row in rows],
            "avg_rerank": [round(row["avg_rerank"] or 0, 3) for row in rows],
            "avg_result_count": [round(row["avg_result_count"] or 0, 1) for row in rows],
            "counts": [row["count"] for row in rows],
            "failed_counts": [row["failed_count"] for row in rows],
        }

    async def get_records(
        self,
        page: int = 1,
        page_size: int = 20,
        user_id: str | None = None,
        flavor: str | None = None,
    ) -> dict:
        """Paginated query records with optional user/flavor filtering."""
        offset = (page - 1) * page_size
        where, params = _where(user_id=user_id, flavor=flavor)
        async with get_db() as db:
            async with db.execute(
                f"""SELECT id, session_id, query, search_mode, search_mode_hyde,
                          result_count, rerank_avg_score, rerank_top_score,
                          retrieval_wall_ms, first_token_ms, generate_ms, total_ms,
                          status, error_code, retrieved_chunks, citations,
                          retrieval_flavor, strict_evidence, fallback_used,
                          groundedness_score, endpoint, timings_json, settings_json,
                          result_shape_json, fallback_json, token_usage_json,
                          user_id, created_at
                   FROM query_run_stats {where}
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (*params, page_size, offset),
            ) as cursor:
                rows = await cursor.fetchall()
                records = [_augment_record(dict(row)) for row in rows]

            count_sql = f"SELECT COUNT(*) as total FROM query_run_stats {where}"
            async with db.execute(count_sql, params) as cursor:
                total = (await cursor.fetchone())["total"]

        return {
            "records": records,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_record_detail(self, record_id: int, user_id: str | None = None) -> dict | None:
        """Fetch one query run with decoded observability payloads."""
        where, params = _where(user_id=user_id, extra="id = ?")
        async with get_db() as db:
            async with db.execute(
                f"""SELECT id, session_id, query, search_mode, search_mode_hyde,
                          result_count, rerank_avg_score, rerank_top_score,
                          retrieval_wall_ms, first_token_ms, generate_ms, total_ms,
                          status, error_code, retrieved_chunks, citations,
                          retrieval_flavor, strict_evidence, fallback_used,
                          groundedness_score, endpoint, timings_json, settings_json,
                          result_shape_json, fallback_json, token_usage_json,
                          user_id, created_at
                   FROM query_run_stats {where}
                   LIMIT 1""",
                (*params, record_id),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return _detail_record(dict(row))

    async def get_latency_breakdown(self, user_id: str | None = None) -> dict:
        """Latency p50/p95 grouped by flavor/status/endpoint plus stage summaries."""
        where, params = _where(user_id=user_id)
        async with get_db() as db:
            async with db.execute(
                f"""SELECT retrieval_flavor, status, endpoint, total_ms, timings_json
                   FROM query_run_stats {where}
                   ORDER BY created_at DESC""",
                params,
            ) as cursor:
                rows = [dict(row) for row in await cursor.fetchall()]

        return {
            "by_flavor": _latency_group(rows, "retrieval_flavor", default_keys=FLAVORS),
            "by_status": _latency_group(rows, "status"),
            "by_endpoint": _latency_group(rows, "endpoint"),
            "stages": _stage_latency(rows),
        }


def _json_text(value: list[dict] | str | None) -> str:
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _json_object_text(value: dict[str, Any] | str | None) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json_dumps(value)


def _augment_record(row: dict) -> dict:
    """Add compact decoded observability fields while preserving raw JSON strings."""
    timings = _json_obj(row.get("timings_json"))
    result_shape = _json_obj(row.get("result_shape_json"))
    token_usage = _json_obj(row.get("token_usage_json"))
    fallback = _json_obj(row.get("fallback_json"))
    settings = _json_obj(row.get("settings_json"))
    slowest = _slowest_stage(timings)
    row.update({
        "timings": timings,
        "resolved_settings": settings,
        "result_shape": result_shape,
        "fallback_details": fallback,
        "token_usage": token_usage,
        "slowest_stage": slowest,
        "model": token_usage.get("model", ""),
        "total_tokens": token_usage.get("total_tokens"),
    })
    return row


def _detail_record(row: dict) -> dict:
    row = _augment_record(row)
    row["retrieved_chunks_list"] = _json_list(row.get("retrieved_chunks"))
    row["citations_list"] = _json_list(row.get("citations"))
    row["observability"] = {
        "endpoint": row.get("endpoint", ""),
        "timings_ms": row["timings"],
        "resolved_settings": row["resolved_settings"],
        "result_shape": row["result_shape"],
        "fallback_info": row["fallback_details"],
        "token_usage": row["token_usage"],
    }
    return row


def _json_obj(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _slowest_stage(timings: dict) -> dict:
    candidates = {}
    for key, value in timings.items():
        if key in {"total", "retrieval_wall"}:
            continue
        ms = _int_value(value)
        if ms is not None:
            candidates[str(key)] = ms
    if not candidates:
        return {}
    key, value = max(candidates.items(), key=lambda item: item[1])
    return {"key": key, "ms": value}


def _latency_group(rows: list[dict], field: str, default_keys: tuple[str, ...] = ()) -> dict:
    if field not in LATENCY_GROUP_FIELDS:
        raise ValueError(f"Unsupported latency group field: {field}")
    grouped: dict[str, list[int]] = {key: [] for key in default_keys}
    for row in rows:
        value = str(row.get(field) or "unknown")
        ms = _int_value(row.get("total_ms"))
        if ms is None or ms <= 0:
            continue
        grouped.setdefault(value, []).append(ms)
    return {key: _latency_metric(values) for key, values in grouped.items()}


def _stage_latency(rows: list[dict]) -> dict:
    grouped: dict[str, list[int]] = {}
    for row in rows:
        timings = _json_obj(row.get("timings_json"))
        for key, value in timings.items():
            ms = _int_value(value)
            if ms is None or ms < 0:
                continue
            grouped.setdefault(str(key), []).append(ms)
    return {key: _latency_metric(values) for key, values in sorted(grouped.items())}


def _latency_metric(values: list[int]) -> dict:
    return {
        "count": len(values),
        "p50_ms": _p50(values),
        "p95_ms": _p95(values),
    }


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _where(
    *,
    user_id: str | None = None,
    flavor: str | None = None,
    extra: str = "",
) -> tuple[str, tuple]:
    clauses: list[str] = []
    params: list[Any] = []
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if flavor:
        clauses.append("retrieval_flavor = ?")
        params.append(flavor)
    if extra:
        clauses.append(extra)
    if not clauses:
        return "", tuple()
    return "WHERE " + " AND ".join(clauses), tuple(params)


def _metric_row(row: dict | None, p95_ms: int) -> dict:
    if not row:
        return {
            "count": 0,
            "success_count": 0,
            "failed_count": 0,
            "success_rate": 0,
            "avg_rerank": 0,
            "avg_results": 0,
            "p95_ms": 0,
            "fallback_count": 0,
            "fallback_ratio": 0,
        }
    count = row["count"] or 0
    success_count = row["success_count"] or 0
    fallback_count = row["fallback_count"] or 0
    return {
        "count": count,
        "success_count": success_count,
        "failed_count": row["failed_count"] or 0,
        "success_rate": round(success_count / count, 3) if count else 0,
        "avg_rerank": round(row["avg_rerank"] or 0, 3),
        "avg_results": round(row["avg_results"] or 0, 1),
        "p95_ms": p95_ms,
        "fallback_count": fallback_count,
        "fallback_ratio": round(fallback_count / success_count, 3) if success_count else 0,
    }


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def _p50(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.50) - 1)
    return ordered[index]


query_stats_service = QueryStatsService()
