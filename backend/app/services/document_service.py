"""通用文档导入服务。"""

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

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
    "chunk_count, image_count, created_at, updated_at"
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

    chunks_source = "none"
    chunks: list[dict] = []

    try:
        chunks = await asyncio.to_thread(_sync_query_milvus_chunks, document_id)
        if chunks:
            chunks_source = "milvus"
    except Exception:
        logger.warning("查询 Milvus chunks 失败 document_id=%s", document_id, exc_info=True)

    if not chunks:
        chunks = _load_parsed_chunks(document_id)
        if chunks:
            chunks_source = "parsed_artifact"

    return {
        "chunks_source": chunks_source,
        "document": doc,
        "chunks": [
            _normalize_chunk(row, document_id, idx)
            for idx, row in enumerate(_sort_chunks(chunks), start=1)
        ],
    }


_ALLOWED_STATUS_FIELDS = frozenset({
    "chunk_count", "image_count",
    "error_msg", "error_code",
    "retry_count", "last_failed_stage",
    "cleanup_status", "entity_name",
})


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


async def process_document(document_id: str):
    """后台执行通用导入流程。"""
    doc = await get_document(document_id)
    if not doc:
        return
    if not os.path.isfile(doc["source_path"]):
        await update_document_status(
            document_id, "failed",
            error_msg="文件不存在", error_code="UNKNOWN_ERROR",
            last_failed_stage="pre_check",
        )
        await append_error_event(document_id, "pre_check", "UNKNOWN_ERROR", "文件不存在")
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


def _sync_process_document(doc: dict) -> dict:
    """同步执行导入流程，通过 config 传 status_updater 给 LangGraph 节点。"""
    from app.rag.ingestion.graph import run_ingestion_graph

    config = {
        "configurable": {
            "status_updater": lambda doc_id, status: _sync_update_status(doc_id, status),
        }
    }
    return run_ingestion_graph(doc, entity_name=doc.get("entity_name", ""), config=config)


def _sync_update_status(document_id: str, status: str, **kwargs):
    """线程内同步更新状态。"""
    async def _update():
        await update_document_status(document_id, status, **kwargs)

    asyncio.run(_update())


async def delete_document(document_id: str) -> str:
    """删除文档。返回 "deleted" | "partial" | "not_found"。

    - deleted: Milvus + 本地 + DB 全部清理
    - partial: Milvus 失败，本地清理但 DB 保留（cleanup_status=milvus_delete_failed）
    - not_found: 文档不存在
    """
    doc = await get_document(document_id)
    if not doc:
        return "not_found"

    milvus_ok = True
    try:
        await asyncio.to_thread(_sync_delete_from_milvus, document_id)
    except Exception as exc:
        milvus_ok = False
        logger.warning("Milvus 删除失败 document_id=%s: %s", document_id, exc)
        from app.errors import classify_error
        code = classify_error(exc)
        await update_document_status(
            document_id, doc["status"],
            cleanup_status="milvus_delete_failed",
            error_code=code.value, error_msg=str(exc)[:1000],
        )
        await append_error_event(document_id, "delete_cleanup", code.value, str(exc)[:2000])

    _delete_local_artifacts(document_id)
    _invalidate_entity_cache()

    if milvus_ok:
        await delete_document_record(document_id)
        return "deleted"
    return "partial"


async def repair_delete_document(document_id: str) -> str:
    """修复 milvus_delete_failed 的文档：重试 Milvus 删除 + 清理 DB。

    返回 "deleted"。Milvus 仍失败则 raise。
    """
    doc = await get_document(document_id)
    if not doc or doc.get("cleanup_status") != "milvus_delete_failed":
        raise ValueError("文档不处于可修复删除状态")

    # 重试 Milvus 删除
    await asyncio.to_thread(_sync_delete_from_milvus, document_id)

    # Milvus 成功 → 清理本地（幂等）+ 删 DB
    _delete_local_artifacts(document_id)
    _invalidate_entity_cache()
    await delete_document_record(document_id)
    return "deleted"


def _delete_local_artifacts(document_id: str):
    """删除文档的本地文件（upload + parsed 目录）。幂等。"""
    for path in (
        os.path.join(settings.GENERAL_UPLOAD_DIR, document_id),
        os.path.join(settings.GENERAL_PARSED_DIR, document_id),
    ):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def _sync_delete_from_milvus(document_id: str):
    from app.rag.vectorstores.general_milvus import delete_by_document_id

    delete_by_document_id(document_id)


def _sync_query_milvus_chunks(document_id: str) -> list[dict]:
    from app.rag.vectorstores.general_milvus import query_chunks_by_document_id

    return query_chunks_by_document_id(document_id)


def _load_parsed_chunks(document_id: str) -> list[dict]:
    chunks_path = Path(settings.GENERAL_PARSED_DIR) / document_id / "chunks.json"
    if not chunks_path.is_file():
        return []
    try:
        data = json.loads(chunks_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("读取 parsed chunks 失败 document_id=%s path=%s", document_id, chunks_path, exc_info=True)
        return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _normalize_chunk(row: dict, document_id: str, sequence_index: int) -> dict:
    image_paths = row.get("image_paths", [])
    if isinstance(image_paths, str):
        try:
            image_paths = json.loads(image_paths or "[]")
        except json.JSONDecodeError:
            image_paths = []
    if not isinstance(image_paths, list):
        image_paths = []

    content = row.get("content", "") or ""
    source_type = row.get("source_type", "text") or "text"
    table_id = row.get("table_id") or ""
    part = row.get("part")
    chunk_key = row.get("chunk_key") or _derive_chunk_key(
        document_id=document_id,
        source_type=source_type,
        table_id=table_id,
        part=part,
        sequence_index=sequence_index,
    )

    return {
        "chunk_key": chunk_key,
        "sequence": sequence_index,
        "milvus_chunk_id": row.get("chunk_id"),
        "document_id": row.get("document_id") or document_id,
        "file_title": row.get("file_title", ""),
        "entity_name": row.get("entity_name", ""),
        "content": content,
        "title": row.get("title", ""),
        "parent_title": row.get("parent_title", ""),
        "section_title": row.get("section_title", ""),
        "part": part,
        "page": row.get("page"),
        "source_type": source_type,
        "table_id": row.get("table_id"),
        "table_title": row.get("table_title"),
        "raw_table_path": row.get("raw_table_path"),
        "table_tokens": row.get("table_tokens"),
        "image_paths": image_paths,
        "content_length": len(content),
    }


def _sort_chunks(chunks: list[dict]) -> list[dict]:
    def _key(row: dict):
        page = row.get("page")
        page_key = page if isinstance(page, int) else 10**9
        chunk_id = row.get("chunk_id")
        chunk_key = row.get("chunk_key") or ""
        id_key = chunk_id if isinstance(chunk_id, int) else 10**9
        return (page_key, chunk_key, id_key)

    return sorted(chunks, key=_key)


def _derive_chunk_key(
    document_id: str,
    source_type: str,
    table_id: str,
    part: object,
    sequence_index: int,
) -> str:
    part_value = "" if part is None else str(part)
    return f"{document_id}:{source_type}:{table_id}:{part_value}:{sequence_index:04d}"


def _invalidate_entity_cache():
    from app.rag.query.entity_cache import invalidate
    invalidate()
