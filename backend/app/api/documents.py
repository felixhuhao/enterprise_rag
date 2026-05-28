"""通用文档导入 API。"""

import asyncio
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Response, UploadFile
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
    ".zip": "md_zip",
}

# Magic bytes: { file_type: (offset, expected_bytes) }
_FILE_SIGNATURES = {
    "pdf": (0, b"%PDF-"),
    "zip": (0, b"PK\x03\x04"),
}


def _validate_file_magic(path: str, file_type: str, upload_dir: str):
    """校验文件头 magic bytes，防止改后缀绕过。MD/Markdown 纯文本无特征，跳过。"""
    if file_type == "md":
        return
    sig_key = "zip" if file_type == "md_zip" else file_type
    offset, expected = _FILE_SIGNATURES[sig_key]
    with open(path, "rb") as f:
        f.seek(offset)
        header = f.read(len(expected))
    if header != expected:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="文件内容与扩展名不匹配")


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
        raise HTTPException(status_code=400, detail="仅支持 PDF、MD、Markdown、ZIP 文件")

    document_id = uuid.uuid4().hex
    upload_dir = os.path.join(settings.GENERAL_UPLOAD_DIR, document_id)
    os.makedirs(upload_dir, exist_ok=True)

    original_name = "original.pdf" if file_type == "pdf" else "original.md"
    if file_type == "md_zip":
        original_name = "original.zip"
    source_path = os.path.abspath(os.path.join(upload_dir, original_name))

    # Streaming write + size limit
    max_bytes = settings.UPLOAD_MAX_SIZE_MB * 1024 * 1024
    total = 0
    with open(source_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)  # 1 MB chunks
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                # 清理已写入的文件
                f.close()
                os.remove(source_path)
                os.rmdir(upload_dir)
                raise HTTPException(
                    status_code=400,
                    detail=f"文件超过 {settings.UPLOAD_MAX_SIZE_MB}MB 限制",
                )
            f.write(chunk)

    # Magic bytes 校验：防止改后缀绕过
    _validate_file_magic(source_path, file_type, upload_dir)

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


@router.get("/documents/{document_id}/chunks")
async def get_document_chunks(document_id: str, _: None = Depends(verify_token)):
    """获取文档元数据和 chunk 列表。Milvus 无结果时回退到 parsed chunks 产物。"""
    payload = await document_service.get_document_chunks(document_id)
    if not payload:
        raise HTTPException(status_code=404, detail="文档不存在")
    return payload


@router.get("/documents/{document_id}/related")
async def get_related_documents(document_id: str, _: None = Depends(verify_token)):
    """返回同 entity_name 的相关文档列表。"""
    # TODO: apply document ACL filter once permission-aware retrieval is added.
    return await document_service.list_related_documents(document_id)


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

    # failed 文档走 /retry 端点的安全网逻辑
    if doc["status"] == "failed":
        raise HTTPException(status_code=400, detail="文档状态为 failed，请使用 /retry 端点重试")

    # 先原子改状态，防止连点重复提交
    await document_service.update_document_status(document_id, "processing")
    background_tasks.add_task(document_service.process_document, document_id)
    return {"ok": True, "message": "Document processing started"}


MAX_RETRIES = 3


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

    retry_count = doc.get("retry_count", 0) or 0
    if retry_count >= MAX_RETRIES:
        raise HTTPException(status_code=429, detail=f"重试次数已达上限({MAX_RETRIES})")

    # 重试前清理 Milvus 中可能残留的旧向量——失败则阻断，避免重复向量
    try:
        await asyncio.to_thread(document_service._sync_delete_from_milvus, document_id)
    except Exception as exc:
        from app.errors import classify_error
        code = classify_error(exc)
        await document_service.append_error_event(document_id, "pre_retry_cleanup", code.value, str(exc))
        raise HTTPException(status_code=503, detail="Milvus 向量清理失败，请稍后重试")

    await document_service.update_document_status(
        document_id, "processing",
        retry_count=retry_count + 1,
        error_msg="", error_code="",
    )
    background_tasks.add_task(document_service.process_document, document_id)
    return {"ok": True, "message": "Document retry started"}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, response: Response, _: None = Depends(verify_token)):
    """删除通用文档。Milvus 清理失败时返回 202 partial。"""
    doc = await document_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc["status"] in document_service.PROCESSING_STATUSES:
        raise HTTPException(status_code=409, detail="文档正在处理中，无法删除，请等待处理完成")

    result = await document_service.delete_document(document_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="文档不存在")
    if result == "partial":
        response.status_code = 202
        return {"ok": True, "status": "partial", "detail": "向量数据清理失败，请稍后使用修复功能"}
    return {"ok": True, "status": "deleted"}


@router.post("/documents/{document_id}/repair-delete")
async def repair_delete(document_id: str, _: None = Depends(verify_token)):
    """修复 milvus_delete_failed 状态的文档：重试 Milvus 删除 + 清理 DB。"""
    try:
        await document_service.repair_delete_document(document_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as exc:
        from app.errors import classify_error
        code = classify_error(exc)
        await document_service.append_error_event(document_id, "repair_delete", code.value, str(exc))
        raise HTTPException(status_code=503, detail="Milvus 清理仍失败，请稍后重试")
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
