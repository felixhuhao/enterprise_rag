"""Durable job records for long-running backend operations."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from app.core import database

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_CANCELED = "canceled"

TERMINAL_STATUSES = {JOB_STATUS_SUCCEEDED, JOB_STATUS_FAILED, JOB_STATUS_CANCELED}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_job_id() -> str:
    return f"job_{secrets.token_hex(12)}"


def _row_to_dict(row) -> dict[str, Any] | None:
    return dict(row) if row else None


async def create_job(
    *,
    job_type: str,
    resource_type: str = "",
    resource_id: str = "",
    created_by: str = "",
    progress_total: int = 0,
    message: str = "",
    attempt_count: int = 1,
) -> dict[str, Any]:
    """Create a queued job record and return it."""
    now = _now()
    job_id = _new_job_id()
    async with database.get_db() as db:
        await db.execute(
            """
            INSERT INTO jobs (
                job_id, job_type, status, resource_type, resource_id,
                progress_current, progress_total, message, error_code,
                error_detail, attempt_count, created_by, created_at,
                started_at, finished_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_type,
                JOB_STATUS_QUEUED,
                resource_type,
                resource_id,
                0,
                max(0, int(progress_total or 0)),
                message,
                "",
                "",
                max(1, int(attempt_count or 1)),
                created_by,
                now,
                "",
                "",
                now,
            ),
        )
        await db.commit()
    return await get_job(job_id) or {"job_id": job_id}


async def get_job(job_id: str) -> dict[str, Any] | None:
    async with database.get_db() as db:
        async with db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)) as cursor:
            return _row_to_dict(await cursor.fetchone())


async def list_jobs(
    *,
    status: str = "",
    job_type: str = "",
    resource_type: str = "",
    resource_id: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if job_type:
        where.append("job_type = ?")
        params.append(job_type)
    if resource_type:
        where.append("resource_type = ?")
        params.append(resource_type)
    if resource_id:
        where.append("resource_id = ?")
        params.append(resource_id)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    safe_limit = min(max(1, int(limit or 50)), 200)
    async with database.get_db() as db:
        async with db.execute(
            f"""
            SELECT * FROM jobs
            {where_sql}
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (*params, safe_limit),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def mark_job_running(job_id: str, *, message: str = "") -> dict[str, Any] | None:
    now = _now()
    fields: dict[str, Any] = {
        "status": JOB_STATUS_RUNNING,
        "updated_at": now,
    }
    if message:
        fields["message"] = message
    job = await get_job(job_id)
    if job and not job.get("started_at"):
        fields["started_at"] = now
    await _update_job(job_id, fields)
    return await get_job(job_id)


async def update_job_progress(
    job_id: str,
    *,
    progress_current: int | None = None,
    progress_total: int | None = None,
    message: str = "",
) -> dict[str, Any] | None:
    fields: dict[str, Any] = {"updated_at": _now()}
    if progress_current is not None:
        fields["progress_current"] = max(0, int(progress_current))
    if progress_total is not None:
        fields["progress_total"] = max(0, int(progress_total))
    if message:
        fields["message"] = message
    await _update_job(job_id, fields)
    return await get_job(job_id)


async def mark_job_succeeded(job_id: str, *, message: str = "") -> dict[str, Any] | None:
    now = _now()
    fields: dict[str, Any] = {
        "status": JOB_STATUS_SUCCEEDED,
        "error_code": "",
        "error_detail": "",
        "finished_at": now,
        "updated_at": now,
    }
    if message:
        fields["message"] = message
    await _update_job(job_id, fields)
    return await get_job(job_id)


async def mark_job_failed(
    job_id: str,
    *,
    error_code: str,
    error_detail: str,
    message: str = "",
) -> dict[str, Any] | None:
    now = _now()
    await _update_job(
        job_id,
        {
            "status": JOB_STATUS_FAILED,
            "message": message or error_code,
            "error_code": error_code,
            "error_detail": error_detail[:4000],
            "finished_at": now,
            "updated_at": now,
        },
    )
    return await get_job(job_id)


async def mark_job_canceled(job_id: str, *, message: str = "canceled") -> dict[str, Any] | None:
    now = _now()
    await _update_job(
        job_id,
        {
            "status": JOB_STATUS_CANCELED,
            "message": message,
            "finished_at": now,
            "updated_at": now,
        },
    )
    return await get_job(job_id)


async def mark_interrupted_jobs_failed() -> int:
    """Mark stale running jobs as failed during app startup."""
    now = _now()
    async with database.get_db() as db:
        cursor = await db.execute(
            """
            UPDATE jobs
            SET status = ?, message = ?, error_code = ?, error_detail = ?,
                finished_at = ?, updated_at = ?
            WHERE status = ?
            """,
            (
                JOB_STATUS_FAILED,
                "interrupted during previous run",
                "JOB_INTERRUPTED",
                "interrupted during previous run",
                now,
                now,
                JOB_STATUS_RUNNING,
            ),
        )
        await db.commit()
        return cursor.rowcount


async def _update_job(job_id: str, fields: dict[str, Any]) -> None:
    allowed = {
        "status",
        "progress_current",
        "progress_total",
        "message",
        "error_code",
        "error_detail",
        "attempt_count",
        "started_at",
        "finished_at",
        "updated_at",
    }
    clean = {key: value for key, value in fields.items() if key in allowed}
    if not clean:
        return
    assignments = ", ".join(f"{key} = ?" for key in clean)
    async with database.get_db() as db:
        await db.execute(
            f"UPDATE jobs SET {assignments} WHERE job_id = ?",
            (*clean.values(), job_id),
        )
        await db.commit()
