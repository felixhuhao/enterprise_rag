"""
知识库服务模块

编排 PDF 解析 → Markdown 拆分 → Milvus 入库的完整流程。
通过 asyncio.to_thread 调用同步函数，避免阻塞事件循环。
"""

import os
import asyncio
import logging
from datetime import datetime

from app.config import settings
from app.core.database import get_db

logger = logging.getLogger(__name__)


async def create_document_record(filename: str, source: str) -> int:
    """在数据库中创建文档记录，返回文档 ID"""
    now = datetime.now().isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO knowledge_documents (filename, source, status, created_at, updated_at)
               VALUES (?, ?, 'uploaded', ?, ?)""",
            (filename, source, now, now),
        )
        await db.commit()
        return cursor.lastrowid


async def get_document(doc_id: int) -> dict | None:
    """根据 ID 获取文档记录"""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM knowledge_documents WHERE id = ?", (doc_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def list_documents() -> list[dict]:
    """列出所有文档"""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM knowledge_documents ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def update_document_status(
    doc_id: int, status: str, **kwargs
):
    """更新文档状态"""
    now = datetime.now().isoformat()
    async with get_db() as db:
        sets = ["status = ?", "updated_at = ?"]
        vals = [status, now]
        for key, val in kwargs.items():
            sets.append(f"{key} = ?")
            vals.append(val)
        vals.append(doc_id)
        await db.execute(
            f"UPDATE knowledge_documents SET {', '.join(sets)} WHERE id = ?",
            vals,
        )
        await db.commit()


async def delete_document_record(doc_id: int) -> bool:
    """删除文档记录"""
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM knowledge_documents WHERE id = ?", (doc_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


def _sync_process_pdf(pdf_path: str, source: str, output_dir: str) -> dict:
    """
    同步执行：OCR 解析 → Markdown 拆分 → Milvus 入库

    返回:
        {"doc_count": int, "image_count": int}
    """
    from ocr.parser import do_parse
    from splitters.md_splitter import MarkdownDirSplitter
    from milvus_db.db_operator import do_save_to_milvus

    # Step 1: OCR 解析 PDF → Markdown
    logger.info("开始 OCR 解析: %s", pdf_path)
    do_parse(pdf_path, output_dir)

    # Step 2: Markdown 拆分为 Documents
    images_dir = os.path.join(output_dir, "images")
    splitter = MarkdownDirSplitter(images_output_dir=images_dir)
    documents = splitter.process_md_dir(output_dir, source)
    logger.info("拆分完成，共 %d 个文档片段", len(documents))

    # Step 3: 向量化并写入 Milvus
    do_save_to_milvus(documents)
    logger.info("Milvus 入库完成")

    img_count = sum(1 for d in documents if d.metadata.get("images"))
    return {"doc_count": len(documents), "image_count": img_count}


async def process_document(doc_id: int):
    """
    异步编排文档处理全流程（后台任务调用）

    步骤：解析 → 拆分 → 入库，全程更新数据库状态
    """
    doc = await get_document(doc_id)
    if not doc:
        return

    pdf_path = os.path.join(settings.UPLOAD_DIR, doc["source"])
    if not os.path.isfile(pdf_path):
        await update_document_status(doc_id, "failed", error_msg="文件不存在")
        return

    output_dir = os.path.join(settings.UPLOAD_DIR, f"parsed_{doc_id}")

    try:
        await update_document_status(doc_id, "parsing")
        result = await asyncio.to_thread(
            _sync_process_pdf, pdf_path, doc["source"], output_dir
        )
        await update_document_status(
            doc_id,
            "completed",
            doc_count=result["doc_count"],
            image_count=result["image_count"],
        )
    except Exception as e:
        logger.error("文档处理失败 (id=%s): %s", doc_id, e)
        await update_document_status(doc_id, "failed", error_msg=str(e)[:500])


def _sync_delete_from_milvus(source: str):
    """同步删除 Milvus 中的文档"""
    from milvus_db.db_operator import delete_by_source
    delete_by_source(source)


async def delete_document(doc_id: int) -> bool:
    """删除文档（Milvus + SQLite + 文件）"""
    doc = await get_document(doc_id)
    if not doc:
        return False

    # 从 Milvus 删除（如果已入库）
    if doc["status"] in ("completed", "parsed", "saving"):
        try:
            await asyncio.to_thread(_sync_delete_from_milvus, doc["source"])
        except Exception as e:
            logger.warning("Milvus 删除失败: %s", e)

    # 删除本地文件
    pdf_path = os.path.join(settings.UPLOAD_DIR, doc["source"])
    if os.path.isfile(pdf_path):
        os.remove(pdf_path)

    # 删除数据库记录
    return await delete_document_record(doc_id)
