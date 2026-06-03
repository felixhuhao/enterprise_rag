import asyncio

from app.api.admin_jobs import _format_job
from app.core import database
from app.services import job_service


def run(coro):
    return asyncio.run(coro)


def init_tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    run(database.init_db())
    return db_path


def test_job_service_lifecycle(tmp_path, monkeypatch):
    init_tmp_db(tmp_path, monkeypatch)

    job = run(job_service.create_job(
        job_type="document_ingestion",
        resource_type="document",
        resource_id="doc-1",
        created_by="admin",
        progress_total=4,
        message="queued",
    ))

    assert job["job_id"].startswith("job_")
    assert job["status"] == job_service.JOB_STATUS_QUEUED
    assert job["progress_total"] == 4

    running = run(job_service.mark_job_running(job["job_id"], message="processing"))
    assert running["status"] == job_service.JOB_STATUS_RUNNING
    assert running["started_at"]
    assert running["message"] == "processing"

    updated = run(job_service.update_job_progress(
        job["job_id"],
        progress_current=2,
        progress_total=4,
        message="chunking",
    ))
    assert updated["progress_current"] == 2
    assert updated["progress_total"] == 4
    assert updated["message"] == "chunking"

    jobs = run(job_service.list_jobs(status=job_service.JOB_STATUS_RUNNING))
    assert [item["job_id"] for item in jobs] == [job["job_id"]]

    succeeded = run(job_service.mark_job_succeeded(job["job_id"], message="done"))
    assert succeeded["status"] == job_service.JOB_STATUS_SUCCEEDED
    assert succeeded["finished_at"]
    assert succeeded["message"] == "done"


def test_mark_interrupted_jobs_failed_only_marks_running(tmp_path, monkeypatch):
    init_tmp_db(tmp_path, monkeypatch)
    running = run(job_service.create_job(job_type="eval", resource_type="eval"))
    queued = run(job_service.create_job(job_type="document_ingestion", resource_type="document"))
    run(job_service.mark_job_running(running["job_id"]))

    count = run(job_service.mark_interrupted_jobs_failed())

    assert count == 1
    running_after = run(job_service.get_job(running["job_id"]))
    queued_after = run(job_service.get_job(queued["job_id"]))
    assert running_after["status"] == job_service.JOB_STATUS_FAILED
    assert running_after["error_code"] == "JOB_INTERRUPTED"
    assert queued_after["status"] == job_service.JOB_STATUS_QUEUED


def test_format_job_adds_status_label_and_progress_percent():
    row = {
        "job_id": "job_1",
        "job_type": "eval",
        "status": job_service.JOB_STATUS_RUNNING,
        "resource_type": "eval",
        "resource_id": "eval_1",
        "progress_current": 3,
        "progress_total": 4,
    }

    formatted = _format_job(row)

    assert formatted["status_label"] == "运行中"
    assert formatted["progress_percent"] == 75.0
