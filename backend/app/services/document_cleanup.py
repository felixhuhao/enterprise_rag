"""Document cleanup helpers for local artifacts and Milvus vectors."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from collections.abc import Awaitable, Callable

from app.config import settings

logger = logging.getLogger(__name__)

GetDocumentFn = Callable[[str], Awaitable[dict | None]]
UpdateStatusFn = Callable[..., Awaitable[None]]
AppendErrorFn = Callable[[str, str, str, str], Awaitable[None]]
DeleteRecordFn = Callable[[str], Awaitable[bool]]
DeleteFromMilvusFn = Callable[[str], None]
DeleteLocalArtifactsFn = Callable[[str], None]
InvalidateCacheFn = Callable[[], None]


async def delete_document(
    document_id: str,
    *,
    get_document: GetDocumentFn,
    update_document_status: UpdateStatusFn,
    append_error_event: AppendErrorFn,
    delete_document_record: DeleteRecordFn,
    delete_from_milvus: DeleteFromMilvusFn,
    delete_local_artifacts: DeleteLocalArtifactsFn,
    invalidate_entity_cache: InvalidateCacheFn,
) -> str:
    """Delete document vectors, local artifacts, and DB row."""
    doc = await get_document(document_id)
    if not doc:
        return "not_found"

    milvus_ok = True
    try:
        await asyncio.to_thread(delete_from_milvus, document_id)
    except Exception as exc:
        milvus_ok = False
        logger.warning("Milvus delete failed: document_id=%s: %s", document_id, exc)
        from app.errors import classify_error
        code = classify_error(exc)
        await update_document_status(
            document_id,
            doc["status"],
            cleanup_status="milvus_delete_failed",
            error_code=code.value,
            error_msg=str(exc)[:1000],
        )
        await append_error_event(document_id, "delete_cleanup", code.value, str(exc)[:2000])

    delete_local_artifacts(document_id)
    invalidate_entity_cache()

    if milvus_ok:
        await delete_document_record(document_id)
        return "deleted"
    return "partial"


async def repair_delete_document(
    document_id: str,
    *,
    get_document: GetDocumentFn,
    delete_document_record: DeleteRecordFn,
    delete_from_milvus: DeleteFromMilvusFn,
    delete_local_artifacts: DeleteLocalArtifactsFn,
    invalidate_entity_cache: InvalidateCacheFn,
) -> str:
    """Retry vector cleanup for a previously partial delete, then remove DB row."""
    doc = await get_document(document_id)
    if not doc or doc.get("cleanup_status") != "milvus_delete_failed":
        raise ValueError("文档不处于可修复删除状态")

    await asyncio.to_thread(delete_from_milvus, document_id)
    delete_local_artifacts(document_id)
    invalidate_entity_cache()
    await delete_document_record(document_id)
    return "deleted"


def delete_local_artifacts(document_id: str) -> None:
    """Delete uploaded and parsed artifacts. Idempotent."""
    for path in (
        os.path.join(settings.GENERAL_UPLOAD_DIR, document_id),
        os.path.join(settings.GENERAL_PARSED_DIR, document_id),
    ):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def delete_from_milvus(document_id: str) -> None:
    from app.rag.vectorstores.general_milvus import delete_by_document_id

    delete_by_document_id(document_id)
