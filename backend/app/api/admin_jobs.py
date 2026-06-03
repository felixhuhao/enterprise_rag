"""Admin job status API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import CurrentUser
from app.deps import verify_token
from app.services import job_service

router = APIRouter()

STATUS_LABELS = {
    job_service.JOB_STATUS_QUEUED: "排队中",
    job_service.JOB_STATUS_RUNNING: "运行中",
    job_service.JOB_STATUS_SUCCEEDED: "已完成",
    job_service.JOB_STATUS_FAILED: "失败",
    job_service.JOB_STATUS_CANCELED: "已取消",
}


def _require_admin(current_user: CurrentUser) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员")


def _format_job(job: dict) -> dict:
    progress_total = int(job.get("progress_total") or 0)
    progress_current = int(job.get("progress_current") or 0)
    progress_percent = None
    if progress_total > 0:
        progress_percent = round(min(100, max(0, progress_current / progress_total * 100)), 1)
    status = str(job.get("status") or "")
    return {
        **job,
        "status_label": STATUS_LABELS.get(status, status or "未知"),
        "progress_percent": progress_percent,
    }


@router.get("/admin/jobs")
async def list_jobs(
    status: str = "",
    job_type: str = "",
    resource_type: str = "",
    resource_id: str = "",
    limit: int = Query(default=50, ge=1, le=200),
    current_user: CurrentUser = Depends(verify_token),
):
    _require_admin(current_user)
    jobs = await job_service.list_jobs(
        status=status,
        job_type=job_type,
        resource_type=resource_type,
        resource_id=resource_id,
        limit=limit,
    )
    return {"count": len(jobs), "jobs": [_format_job(job) for job in jobs]}


@router.get("/admin/jobs/{job_id}")
async def get_job(job_id: str, current_user: CurrentUser = Depends(verify_token)):
    _require_admin(current_user)
    job = await job_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"job": _format_job(job)}
