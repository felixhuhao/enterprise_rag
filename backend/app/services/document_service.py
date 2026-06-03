"""通用文档导入服务。"""

import asyncio
import logging
import os
from datetime import datetime

from app.config import settings
from app.core.database import get_db
from app.services import document_chunk_query, document_cleanup, job_service

logger = logging.getLogger(__name__)

PROCESSING_STATUSES = (
    "processing",
    "parsing",
    "reading",
    "normalizing",
    "chunking",
    "enriching",
    "embedding",
    "saving",
)

DOCUMENT_JOB_TOTAL_STEPS = 7
DOCUMENT_JOB_STAGE_PROGRESS = {
    "queued": 0,
    "processing": 1,
    "reading": 2,
    "parsing": 2,
    "normalizing": 3,
    "chunking": 4,
    "enriching": 5,
    "embedding": 6,
    "saving": 7,
    "completed": 7,
}

DOCUMENT_JOB_TYPE_INGESTION = "document_ingestion"
DOCUMENT_JOB_TYPE_RETRY = "document_retry"


async def create_document_record(
    document_id: str,
    filename: str,
    source_path: str,
    file_type: str,
    ingestion_mode: str = "text_only",
    entity_name: str = "",
) -> dict:
    """创建通用文档记录。"""
    now = datetime.now().isoformat()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO general_documents
                (document_id, filename, source_path, file_type, ingestion_mode, entity_name, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'uploaded', ?, ?)
            """,
            (document_id, filename, source_path, file_type, ingestion_mode, entity_name, now, now),
        )
        await db.commit()
    doc = await get_document(document_id)
    if not doc:
        raise RuntimeError("通用文档记录创建失败")
    return doc


async def get_document(document_id: str) -> dict | None:
    """根据 document_id 获取文档记录。"""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM general_documents WHERE document_id = ?", (document_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def list_documents() -> list[dict]:
    """列出通用文档记录。"""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM general_documents ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


_RELATED_COLUMNS = (
    "document_id, filename, file_type, entity_name, status, "
    "chunk_count, image_count, quality_status, quality_warning_count, "
    "parser_version, chunker_version, enrichment_profile, processed_at, "
    "created_at, updated_at"
)


async def list_related_documents(document_id: str, allowed_ids: list[str] | None = None) -> dict:
    """返回同 entity 且用户可见的相关文档列表。allowed_ids=None 表示不限制。"""
    doc = await get_document(document_id)
    if not doc or not doc.get("entity_name"):
        return {"entity": "", "related": []}

    if allowed_ids is not None and not allowed_ids:
        return {"entity": doc["entity_name"], "related": []}

    async with get_db() as db:
        if allowed_ids is None:
            async with db.execute(
                f"SELECT {_RELATED_COLUMNS} FROM general_documents "
                "WHERE entity_name = ? AND document_id != ? "
                "ORDER BY updated_at DESC",
                (doc["entity_name"], document_id),
            ) as cursor:
                rows = await cursor.fetchall()
        else:
            placeholders = ",".join("?" * len(allowed_ids))
            async with db.execute(
                f"SELECT {_RELATED_COLUMNS} FROM general_documents "
                f"WHERE entity_name = ? AND document_id != ? AND document_id IN ({placeholders}) "
                "ORDER BY updated_at DESC",
                (doc["entity_name"], document_id, *allowed_ids),
            ) as cursor:
                rows = await cursor.fetchall()
    return {"entity": doc["entity_name"], "related": [dict(r) for r in rows]}


async def get_document_chunks(document_id: str) -> dict | None:
    """Return document metadata and chunks from Milvus, with parsed artifact fallback."""
    doc = await get_document(document_id)
    if not doc:
        return None

    return await document_chunk_query.get_document_chunks_payload(
        document_id,
        doc,
        query_milvus_chunks=_sync_query_milvus_chunks,
        load_parsed_chunks=_load_parsed_chunks,
        load_quality_report=_load_quality_report,
        normalize_chunk=_normalize_chunk,
        sort_chunks=_sort_chunks,
    )


async def get_document_chunk_by_key(document_id: str, chunk_key: str) -> dict | None:
    """Return one source chunk by stable chunk_key from Milvus or parsed artifacts."""
    if not await get_document(document_id):
        return None

    return await document_chunk_query.get_document_chunk_by_key_payload(
        document_id,
        chunk_key,
        query_milvus_chunk_by_key=_sync_query_milvus_chunk_by_key,
        load_parsed_chunks=_load_parsed_chunks,
        load_quality_report=_load_quality_report,
        normalize_chunk=_normalize_chunk,
        sort_chunks=_sort_chunks,
    )


_ALLOWED_STATUS_FIELDS = frozenset({
    "chunk_count", "image_count",
    "quality_status", "quality_warning_count",
    "parser_version", "chunker_version",
    "enrichment_profile", "processed_at",
    "error_msg", "error_code",
    "retry_count", "last_failed_stage",
    "cleanup_status", "entity_name",
})

_QUALITY_SUMMARY_FIELDS = (
    "quality_status",
    "quality_warning_count",
    "parser_version",
    "chunker_version",
    "enrichment_profile",
    "processed_at",
)


def _quality_status_update_fields(result: dict) -> dict:
    """Return compact quality fields from an ingestion result."""
    return {
        key: result[key]
        for key in _QUALITY_SUMMARY_FIELDS
        if key in result
    }


async def create_document_job(
    document_id: str,
    *,
    job_type: str = DOCUMENT_JOB_TYPE_INGESTION,
    created_by: str = "",
    attempt_count: int = 1,
    message: str = "queued",
) -> dict:
    """Create a durable job record for document processing work."""
    return await job_service.create_job(
        job_type=job_type,
        resource_type="document",
        resource_id=document_id,
        created_by=created_by,
        progress_total=DOCUMENT_JOB_TOTAL_STEPS,
        message=message,
        attempt_count=attempt_count,
    )


async def mark_document_job_retry_cleanup(job_id: str):
    """Mark a retry job as running while pre-cleanup is in progress."""
    if not job_id:
        return
    try:
        await job_service.mark_job_running(job_id, message="pre_retry_cleanup")
        await job_service.update_job_progress(
            job_id,
            progress_current=0,
            progress_total=DOCUMENT_JOB_TOTAL_STEPS,
            message="pre_retry_cleanup",
        )
    except Exception:
        logger.exception("文档 job 更新失败 job_id=%s stage=pre_retry_cleanup", job_id)


async def _safe_mark_document_job_running(job_id: str, status: str = "processing"):
    if not job_id:
        return
    try:
        await job_service.mark_job_running(job_id, message=status)
        await _safe_update_document_job_progress(job_id, status)
    except Exception:
        logger.exception("文档 job 启动状态更新失败 job_id=%s", job_id)


async def _safe_update_document_job_progress(job_id: str, status: str):
    if not job_id:
        return
    try:
        progress = DOCUMENT_JOB_STAGE_PROGRESS.get(status, 1)
        await job_service.update_job_progress(
            job_id,
            progress_current=progress,
            progress_total=DOCUMENT_JOB_TOTAL_STEPS,
            message=status,
        )
    except Exception:
        logger.exception("文档 job 进度更新失败 job_id=%s status=%s", job_id, status)


async def _safe_mark_document_job_succeeded(job_id: str):
    if not job_id:
        return
    try:
        await job_service.update_job_progress(
            job_id,
            progress_current=DOCUMENT_JOB_TOTAL_STEPS,
            progress_total=DOCUMENT_JOB_TOTAL_STEPS,
            message="completed",
        )
        await job_service.mark_job_succeeded(job_id, message="Document processing completed")
    except Exception:
        logger.exception("文档 job 完成状态更新失败 job_id=%s", job_id)


async def mark_document_job_failed(
    job_id: str,
    *,
    error_code: str,
    error_detail: str,
    message: str = "",
):
    if not job_id:
        return
    try:
        await job_service.mark_job_failed(
            job_id,
            error_code=error_code,
            error_detail=error_detail,
            message=message,
        )
    except Exception:
        logger.exception("文档 job 失败状态更新失败 job_id=%s", job_id)


async def update_document_status(document_id: str, status: str, **kwargs):
    """统一更新文档状态，仅允许白名单字段。"""
    bad = set(kwargs) - _ALLOWED_STATUS_FIELDS
    if bad:
        raise ValueError(f"update_document_status: 不允许的字段 {bad}")

    now = datetime.now().isoformat()
    async with get_db() as db:
        sets = ["status = ?", "updated_at = ?"]
        vals = [status, now]
        for key, val in kwargs.items():
            sets.append(f"{key} = ?")
            vals.append(val)
        vals.append(document_id)
        await db.execute(
            f"UPDATE general_documents SET {', '.join(sets)} WHERE document_id = ?",
            vals,
        )
        await db.commit()


async def claim_document_for_processing(document_id: str) -> bool:
    """Atomically move an uploaded document to processing."""
    now = datetime.now().isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE general_documents SET status = 'processing', updated_at = ? "
            "WHERE document_id = ? AND status = 'uploaded'",
            (now, document_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_entity_name(document_id: str, entity_name: str) -> bool:
    """更新 entity_name，仅 uploaded 状态允许。返回是否成功。"""
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE general_documents SET entity_name = ? WHERE document_id = ? AND status = 'uploaded'",
            (entity_name, document_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def append_error_event(document_id: str, stage: str, error_code: str, error_msg: str):
    """追加错误事件到 document_error_events 表。"""
    now = datetime.now().isoformat()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO document_error_events (document_id, stage, error_code, error_msg, created_at) VALUES (?, ?, ?, ?, ?)",
            (document_id, stage, error_code, error_msg[:2000], now),
        )
        await db.commit()


async def mark_interrupted_documents_failed():
    """应用启动时恢复被进程中断的后台任务。"""
    now = datetime.now().isoformat()
    placeholders = ",".join("?" for _ in PROCESSING_STATUSES)
    async with get_db() as db:
        # 查出所有被中断的文档
        async with db.execute(
            f"SELECT document_id, status FROM general_documents WHERE status IN ({placeholders})",
            PROCESSING_STATUSES,
        ) as cursor:
            interrupted = await cursor.fetchall()

        if not interrupted:
            return

        # 批量标记 failed
        await db.execute(
            f"""
            UPDATE general_documents
            SET status = 'failed', error_msg = ?, updated_at = ?,
                last_failed_stage = status
            WHERE status IN ({placeholders})
            """,
            ("interrupted during previous run", now, *PROCESSING_STATUSES),
        )

        # 追加 error events
        for row in interrupted:
            doc = dict(row)
            await db.execute(
                "INSERT INTO document_error_events (document_id, stage, error_code, error_msg, created_at) VALUES (?, ?, ?, ?, ?)",
                (doc["document_id"], doc["status"], "UNKNOWN_ERROR", "interrupted during previous run", now),
            )

        await db.commit()


async def delete_document_record(document_id: str) -> bool:
    """删除通用文档记录。"""
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM general_documents WHERE document_id = ?", (document_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def process_document(document_id: str, job_id: str = ""):
    """后台执行通用导入流程。"""
    await _safe_mark_document_job_running(job_id, "processing")
    doc = await get_document(document_id)
    if not doc:
        await mark_document_job_failed(
            job_id,
            error_code="DOCUMENT_NOT_FOUND",
            error_detail="Document record not found",
            message="document_not_found",
        )
        return
    if not os.path.isfile(doc["source_path"]):
        await update_document_status(
            document_id, "failed",
            error_msg="文件不存在", error_code="UNKNOWN_ERROR",
            last_failed_stage="pre_check",
        )
        await append_error_event(document_id, "pre_check", "UNKNOWN_ERROR", "文件不存在")
        await mark_document_job_failed(
            job_id,
            error_code="UNKNOWN_ERROR",
            error_detail="文件不存在",
            message="pre_check",
        )
        return

    try:
        await update_document_status(document_id, "processing", error_msg="")
        await _safe_update_document_job_progress(job_id, "processing")
        result = await asyncio.to_thread(_sync_process_document, doc, job_id)
        await update_document_status(
            document_id,
            "completed",
            chunk_count=result["chunk_count"],
            image_count=result["image_count"],
            error_msg="",
            **_quality_status_update_fields(result),
        )
        await _safe_mark_document_job_succeeded(job_id)
        _invalidate_entity_cache()
    except Exception as exc:
        logger.exception("通用文档处理失败 document_id=%s", document_id)
        from app.errors import classify_error
        code = classify_error(exc)
        # 推断失败阶段：当前 doc 的 status 就是最后到达的阶段
        current_doc = await get_document(document_id)
        failed_stage = current_doc["status"] if current_doc else "processing"
        await update_document_status(
            document_id, "failed",
            error_msg=str(exc)[:1000], error_code=code.value,
            last_failed_stage=failed_stage,
        )
        await append_error_event(document_id, failed_stage, code.value, str(exc)[:2000])
        await mark_document_job_failed(
            job_id,
            error_code=code.value,
            error_detail=str(exc)[:2000],
            message=failed_stage,
        )


def _sync_process_document(doc: dict, job_id: str = "") -> dict:
    """同步执行导入流程，通过 config 传 status_updater 给 LangGraph 节点。"""
    from app.rag.ingestion.graph import run_ingestion_graph

    config = {
        "configurable": {
            "status_updater": lambda doc_id, status: _sync_update_status(doc_id, status, job_id=job_id),
        }
    }
    return run_ingestion_graph(doc, entity_name=doc.get("entity_name", ""), config=config)


def _sync_update_status(document_id: str, status: str, job_id: str = "", **kwargs):
    """线程内同步更新状态。"""
    async def _update():
        await update_document_status(document_id, status, **kwargs)
        await _safe_update_document_job_progress(job_id, status)

    asyncio.run(_update())


async def delete_document(document_id: str) -> str:
    """删除文档。返回 "deleted" | "partial" | "not_found"。

    - deleted: Milvus + 本地 + DB 全部清理
    - partial: Milvus 失败，本地清理但 DB 保留（cleanup_status=milvus_delete_failed）
    - not_found: 文档不存在
    """
    return await document_cleanup.delete_document(
        document_id,
        get_document=get_document,
        update_document_status=update_document_status,
        append_error_event=append_error_event,
        delete_document_record=delete_document_record,
        delete_from_milvus=_sync_delete_from_milvus,
        delete_local_artifacts=_delete_local_artifacts,
        invalidate_entity_cache=_invalidate_entity_cache,
    )


async def repair_delete_document(document_id: str) -> str:
    """修复 milvus_delete_failed 的文档：重试 Milvus 删除 + 清理 DB。

    返回 "deleted"。Milvus 仍失败则 raise。
    """
    return await document_cleanup.repair_delete_document(
        document_id,
        get_document=get_document,
        delete_document_record=delete_document_record,
        delete_from_milvus=_sync_delete_from_milvus,
        delete_local_artifacts=_delete_local_artifacts,
        invalidate_entity_cache=_invalidate_entity_cache,
    )


def _delete_local_artifacts(document_id: str):
    document_cleanup.delete_local_artifacts(document_id)


def _sync_delete_from_milvus(document_id: str):
    document_cleanup.delete_from_milvus(document_id)


def _sync_query_milvus_chunks(document_id: str) -> list[dict]:
    return document_chunk_query.query_milvus_chunks(document_id)


def _sync_query_milvus_chunk_by_key(document_id: str, chunk_key: str) -> dict | None:
    return document_chunk_query.query_milvus_chunk_by_key(document_id, chunk_key)


def _load_parsed_chunks(document_id: str) -> list[dict]:
    return document_chunk_query.load_parsed_chunks(document_id)


def _load_quality_report(document_id: str) -> dict:
    return document_chunk_query.load_quality_report(document_id)


def _normalize_chunk(row: dict, document_id: str, sequence_index: int) -> dict:
    return document_chunk_query.normalize_chunk(row, document_id, sequence_index)


def _sort_chunks(chunks: list[dict]) -> list[dict]:
    return document_chunk_query.sort_chunks(chunks)


def _invalidate_entity_cache():
    from app.rag.query.entity_cache import invalidate
    invalidate()
