import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api import documents
from app.core.auth import CurrentUser


def run(coro):
    return asyncio.run(coro)


def _user() -> CurrentUser:
    return CurrentUser(user_id="admin", username="Admin", role="admin")


def test_process_document_returns_job_id_and_schedules_background_task():
    background_tasks = BackgroundTasks()
    create_job = AsyncMock(return_value={"job_id": "job-1"})
    with patch("app.api.documents.has_permission", AsyncMock(return_value=True)), \
         patch("app.api.documents.document_service.claim_document_for_processing", AsyncMock(return_value=True)), \
         patch("app.api.documents.document_service.create_document_job", create_job):
        result = run(documents.process_document("doc-1", background_tasks, _user()))

    assert result == {
        "ok": True,
        "message": "Document processing started",
        "job_id": "job-1",
    }
    create_job.assert_awaited_once_with(
        "doc-1",
        job_type=documents.document_service.DOCUMENT_JOB_TYPE_INGESTION,
        created_by="admin",
        message="queued",
    )
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func == documents.document_service.process_document
    assert task.args == ("doc-1", "job-1")


def test_retry_document_returns_job_id_and_schedules_background_task():
    background_tasks = BackgroundTasks()
    create_job = AsyncMock(return_value={"job_id": "job-retry"})
    with patch("app.api.documents.has_permission", AsyncMock(return_value=True)), \
         patch("app.api.documents.document_service.get_document", AsyncMock(return_value={
             "document_id": "doc-1",
             "status": "failed",
             "retry_count": 0,
         })), \
         patch("app.api.documents.document_service.create_document_job", create_job), \
         patch("app.api.documents.document_service.mark_document_job_retry_cleanup", AsyncMock()), \
         patch("app.api.documents.document_service._sync_delete_from_milvus"), \
         patch("app.api.documents.document_service.update_document_status", AsyncMock()):
        result = run(documents.retry_document("doc-1", background_tasks, _user()))

    assert result == {
        "ok": True,
        "message": "Document retry started",
        "job_id": "job-retry",
    }
    create_job.assert_awaited_once_with(
        "doc-1",
        job_type=documents.document_service.DOCUMENT_JOB_TYPE_RETRY,
        created_by="admin",
        attempt_count=1,
        message="queued",
    )
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func == documents.document_service.process_document
    assert task.args == ("doc-1", "job-retry")


def test_retry_document_marks_job_failed_when_pre_cleanup_fails():
    background_tasks = BackgroundTasks()
    mark_failed = AsyncMock()
    with patch("app.api.documents.has_permission", AsyncMock(return_value=True)), \
         patch("app.api.documents.document_service.get_document", AsyncMock(return_value={
             "document_id": "doc-1",
             "status": "failed",
             "retry_count": 0,
         })), \
         patch("app.api.documents.document_service.create_document_job", AsyncMock(return_value={"job_id": "job-retry"})), \
         patch("app.api.documents.document_service.mark_document_job_retry_cleanup", AsyncMock()), \
         patch("app.api.documents.document_service._sync_delete_from_milvus", side_effect=RuntimeError("milvus down")), \
         patch("app.api.documents.document_service.append_error_event", AsyncMock()), \
         patch("app.api.documents.document_service.mark_document_job_failed", mark_failed):
        with pytest.raises(HTTPException) as exc_info:
            run(documents.retry_document("doc-1", background_tasks, _user()))

    assert exc_info.value.status_code == 503
    assert len(background_tasks.tasks) == 0
    mark_failed.assert_awaited_once()
    assert mark_failed.await_args.args == ("job-retry",)
    assert mark_failed.await_args.kwargs["error_code"] == "MILVUS_ERROR"
    assert "milvus down" in mark_failed.await_args.kwargs["error_detail"]
    assert mark_failed.await_args.kwargs["message"] == "pre_retry_cleanup"
