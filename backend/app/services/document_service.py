"""通用文档导入服务。"""

import asyncio
import logging
import os
import shutil
from datetime import datetime

from app.config import settings
from app.core.database import get_db

logger = logging.getLogger(__name__)

PROCESSING_STATUSES = (
    "processing",
    "parsing",
    "reading",
    "normalizing",
    "chunking",
    "embedding",
    "saving",
)


async def create_document_record(
    document_id: str,
    filename: str,
    source_path: str,
    file_type: str,
    ingestion_mode: str = "text_only",
) -> dict:
    """创建通用文档记录。"""
    now = datetime.now().isoformat()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO general_documents
                (document_id, filename, source_path, file_type, ingestion_mode, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'uploaded', ?, ?)
            """,
            (document_id, filename, source_path, file_type, ingestion_mode, now, now),
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


async def update_document_status(document_id: str, status: str, **kwargs):
    """统一更新文档状态，避免节点散落 SQL。"""
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


async def mark_interrupted_documents_failed():
    """应用启动时恢复被进程中断的后台任务。"""
    now = datetime.now().isoformat()
    placeholders = ",".join("?" for _ in PROCESSING_STATUSES)
    async with get_db() as db:
        await db.execute(
            f"""
            UPDATE general_documents
            SET status = 'failed', error_msg = ?, updated_at = ?
            WHERE status IN ({placeholders})
            """,
            ("interrupted during previous run", now, *PROCESSING_STATUSES),
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


async def process_document(document_id: str):
    """后台执行通用导入流程。"""
    doc = await get_document(document_id)
    if not doc:
        return
    if not os.path.isfile(doc["source_path"]):
        await update_document_status(document_id, "failed", error_msg="文件不存在")
        return

    try:
        await update_document_status(document_id, "processing", error_msg="")
        result = await asyncio.to_thread(_sync_process_document, doc)
        await update_document_status(
            document_id,
            "completed",
            chunk_count=result["chunk_count"],
            image_count=result["image_count"],
            error_msg="",
        )
    except Exception as exc:
        logger.exception("通用文档处理失败 document_id=%s", document_id)
        await update_document_status(document_id, "failed", error_msg=str(exc)[:1000])


def _sync_process_document(doc: dict) -> dict:
    """同步执行导入流程，通过 config 传 status_updater 给 LangGraph 节点。"""
    from app.rag.ingestion.graph import run_ingestion_graph

    config = {
        "configurable": {
            "status_updater": lambda doc_id, status: _sync_update_status(doc_id, status),
        }
    }
    return run_ingestion_graph(doc, config=config)


def _sync_update_status(document_id: str, status: str, **kwargs):
    """线程内同步更新状态。"""
    async def _update():
        await update_document_status(document_id, status, **kwargs)

    asyncio.run(_update())


async def delete_document(document_id: str) -> bool:
    """删除通用文档：Milvus + 本地文件 + SQLite。"""
    doc = await get_document(document_id)
    if not doc:
        return False

    try:
        await asyncio.to_thread(_sync_delete_from_milvus, document_id)
    except Exception as exc:
        logger.warning("通用 Milvus 删除失败 document_id=%s: %s", document_id, exc)

    for path in (
        os.path.join(settings.GENERAL_UPLOAD_DIR, document_id),
        os.path.join(settings.GENERAL_PARSED_DIR, document_id),
    ):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    return await delete_document_record(document_id)


def _sync_delete_from_milvus(document_id: str):
    from app.rag.vectorstores.general_milvus import delete_by_document_id

    delete_by_document_id(document_id)
