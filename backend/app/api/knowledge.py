"""
知识库管理 API 端点模块

端点：
- POST /knowledge/upload: 上传 PDF 文件
- GET /knowledge/documents: 列出所有文档
- GET /knowledge/documents/{id}: 获取单个文档状态
- POST /knowledge/documents/{id}/process: 一键解析+入库
- DELETE /knowledge/documents/{id}: 删除文档
"""

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.deps import verify_token
from app.config import settings
from app.services import knowledge_service

router = APIRouter()


@router.post("/knowledge/upload")
async def upload_document(
    file: UploadFile = File(...),
    _: None = Depends(verify_token),
):
    """
    上传 PDF 文件

    接收 PDF 文件，保存到上传目录，创建数据库记录。
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    # 确保上传目录存在
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

    # 生成唯一文件名防止冲突
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(settings.UPLOAD_DIR, unique_name)

    # 保存文件
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # 创建数据库记录
    doc_id = await knowledge_service.create_document_record(
        filename=file.filename,
        source=unique_name,
    )

    doc = await knowledge_service.get_document(doc_id)
    return doc


@router.get("/knowledge/documents")
async def list_documents(_: None = Depends(verify_token)):
    """列出所有知识库文档"""
    return await knowledge_service.list_documents()


@router.get("/knowledge/documents/{doc_id}")
async def get_document(doc_id: int, _: None = Depends(verify_token)):
    """获取单个文档状态（用于轮询）"""
    doc = await knowledge_service.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@router.post("/knowledge/documents/{doc_id}/process")
async def process_document(doc_id: int, _: None = Depends(verify_token)):
    """
    一键处理文档：OCR 解析 → Markdown 拆分 → Milvus 入库

    耗时较长，后台异步执行。前端可通过 GET 接口轮询状态。
    """
    doc = await knowledge_service.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc["status"] not in ("uploaded", "failed"):
        raise HTTPException(status_code=400, detail=f"文档状态为 {doc['status']}，无法处理")

    import asyncio
    asyncio.create_task(knowledge_service.process_document(doc_id))

    return {"ok": True, "message": "文档处理已启动"}


@router.delete("/knowledge/documents/{doc_id}")
async def delete_document(doc_id: int, _: None = Depends(verify_token)):
    """删除文档（Milvus + SQLite + 本地文件）"""
    if not await knowledge_service.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"ok": True}
