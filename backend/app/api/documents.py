"""通用文档导入 API。"""

import asyncio
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import settings
from app.deps import verify_token
from app.rag.ingestion.service import extract_entity_name
from app.services import document_service

router = APIRouter()

SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".md": "md",
    ".markdown": "md",
}


class UpdateDocumentRequest(BaseModel):
    entity_name: str = ""


@router.get("/documents/suggest-metadata")
async def suggest_metadata(filename: str, _: None = Depends(verify_token)):
    """根据文件名建议 entity_name。"""
    return {"suggested_entity_name": extract_entity_name(filename)}


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    ingestion_mode: str = Form("text_only"),
    entity_name: str = Form(""),
    _: None = Depends(verify_token),
):
    """上传 PDF/Markdown，创建通用文档记录，不立即处理。"""
    if ingestion_mode != "text_only":
        raise HTTPException(status_code=400, detail="当前仅支持 text_only ingestion_mode")

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    ext = os.path.splitext(file.filename)[1].lower()
    file_type = SUPPORTED_EXTENSIONS.get(ext)
    if not file_type:
        raise HTTPException(status_code=400, detail="仅支持 PDF、MD、Markdown 文件")

    document_id = uuid.uuid4().hex
    upload_dir = os.path.join(settings.GENERAL_UPLOAD_DIR, document_id)
    os.makedirs(upload_dir, exist_ok=True)

    original_name = "original.pdf" if file_type == "pdf" else "original.md"
    source_path = os.path.abspath(os.path.join(upload_dir, original_name))
    content = await file.read()
    with open(source_path, "wb") as f:
        f.write(content)

    return await document_service.create_document_record(
        document_id=document_id,
        filename=file.filename,
        source_path=source_path,
        file_type=file_type,
        ingestion_mode=ingestion_mode,
        entity_name=entity_name,
    )


@router.get("/documents")
async def list_documents(_: None = Depends(verify_token)):
    """列出通用文档记录。"""
    return await document_service.list_documents()


@router.get("/documents/{document_id}")
async def get_document(document_id: str, _: None = Depends(verify_token)):
    """获取单个通用文档状态。"""
    doc = await document_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: str,
    body: UpdateDocumentRequest,
    _: None = Depends(verify_token),
):
    """更新文档元数据（仅 uploaded 状态可修改）。"""
    ok = await document_service.update_entity_name(document_id, body.entity_name)
    if not ok:
        doc = await document_service.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")
        raise HTTPException(status_code=409, detail=f"文档状态为 {doc['status']}，无法修改")
    return {"ok": True}


@router.post("/documents/{document_id}/process")
async def process_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_token),
):
    """启动后台导入任务。"""
    doc = await document_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc["status"] not in ("uploaded", "failed"):
        raise HTTPException(status_code=400, detail=f"文档状态为 {doc['status']}，无法处理")

    # 先原子改状态，防止连点重复提交
    await document_service.update_document_status(document_id, "processing")
    background_tasks.add_task(document_service.process_document, document_id)
    return {"ok": True, "message": "Document processing started"}


@router.post("/documents/{document_id}/retry")
async def retry_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_token),
):
    """重试 failed 状态的通用文档。"""
    doc = await document_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc["status"] != "failed":
        raise HTTPException(status_code=400, detail=f"文档状态为 {doc['status']}，无法 retry")

    # 重试前清理 Milvus 中可能残留的旧向量
    try:
        await asyncio.to_thread(document_service._sync_delete_from_milvus, document_id)
    except Exception:
        pass

    await document_service.update_document_status(document_id, "processing")
    background_tasks.add_task(document_service.process_document, document_id)
    return {"ok": True, "message": "Document retry started"}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, _: None = Depends(verify_token)):
    """删除通用文档。"""
    doc = await document_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc["status"] in document_service.PROCESSING_STATUSES:
        raise HTTPException(status_code=409, detail="文档正在处理中，无法删除，请等待处理完成")

    if not await document_service.delete_document(document_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"ok": True}


ALLOWED_ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _verify_asset_token(token: str | None, authorization: str | None):
    """Asset 接口鉴权：支持 query param token 或 Bearer header。"""
    import hmac
    expected = settings.API_TOKEN
    if token and hmac.compare_digest(token, expected):
        return
    if authorization:
        expected_header = f"Bearer {expected}"
        if hmac.compare_digest(authorization, expected_header):
            return
    raise HTTPException(status_code=401, detail="Invalid token")


@router.get("/documents/{document_id}/assets/{asset_path:path}")
async def get_document_asset(
    document_id: str,
    asset_path: str,
    token: str | None = None,
    authorization: str | None = Header(None),
):
    """安全提供文档解析产物（图片等）。支持 ?token=xxx 或 Authorization header。"""
    _verify_asset_token(token, authorization)

    base_dir = (Path(settings.GENERAL_PARSED_DIR).resolve() / document_id).resolve()
    target = (base_dir / asset_path).resolve()

    # 路径穿越检查
    try:
        target.relative_to(base_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid asset path")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")

    if target.suffix.lower() not in ALLOWED_ASSET_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported asset type")

    return FileResponse(str(target))
