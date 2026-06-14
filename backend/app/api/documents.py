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
from app.core.auth import CurrentUser, can_write_entity, get_allowed_document_ids, has_permission
from app.core.database import get_db
from app.core.entity import canonicalize_entity_name, normalize_entity_name
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


async def _require_write(user: CurrentUser, document_id: str):
    """Check write permission: 404 if invisible, 403 if read-only."""
    if user.role == "admin":
        return
    if not await has_permission(user, document_id, "read"):
        raise HTTPException(status_code=404, detail="文档不存在")
    if not await has_permission(user, document_id, "write"):
        raise HTTPException(status_code=403, detail="无权修改该文档（需要写权限）")


class UpdateDocumentRequest(BaseModel):
    entity_name: str = ""


@router.post("/documents/{document_id}/grant", status_code=410)
async def grant_document_access():
    """Deprecated: per-document grants retired. Use POST /admin/acl/grant."""
    raise HTTPException(status_code=410, detail="文档级授权已停用，请使用实体级授权 POST /admin/acl/grant")


@router.get("/documents/suggest-metadata")
async def suggest_metadata(filename: str, current_user: CurrentUser = Depends(verify_token)):
    """根据文件名建议 entity_name。"""
    return {"suggested_entity_name": extract_entity_name(filename)}


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    ingestion_mode: str = Form("text_only"),
    entity_name: str = Form(""),
    current_user: CurrentUser = Depends(verify_token),
):
    """上传 PDF/Markdown，自动授予上传者 owner 权限。"""
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

    # Entity validation: normalize → canonicalize → write-permission check
    normalized_entity = normalize_entity_name(entity_name)
    if normalized_entity:
        async with get_db() as db:
            canonical_entity = await canonicalize_entity_name(normalized_entity, db)
    else:
        canonical_entity = ""
    if not canonical_entity and current_user.role != "admin":
        raise HTTPException(status_code=400, detail="entity_name 不能为空")
    if canonical_entity and not await can_write_entity(current_user, canonical_entity):
        raise HTTPException(status_code=403, detail=f"无权上传到实体 '{canonical_entity}'")

    doc = await document_service.create_document_record(
        document_id=document_id,
        filename=file.filename,
        source_path=source_path,
        file_type=file_type,
        ingestion_mode=ingestion_mode,
        entity_name=canonical_entity,
        uploaded_by=current_user.user_id,
    )
    return doc


@router.get("/documents")
async def list_documents(current_user: CurrentUser = Depends(verify_token)):
    """列出当前用户可见的文档。"""
    docs = await document_service.list_documents()
    allowed = await get_allowed_document_ids(current_user)
    if allowed is None:
        return docs
    allowed_set = set(allowed)
    return [d for d in docs if d["document_id"] in allowed_set]


@router.get("/documents/{document_id}")
async def get_document(document_id: str, current_user: CurrentUser = Depends(verify_token)):
    """获取单个通用文档状态。"""
    if not await has_permission(current_user, document_id, "read"):
        raise HTTPException(status_code=404, detail="文档不存在")
    doc = await document_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@router.get("/documents/{document_id}/chunks")
async def get_document_chunks(document_id: str, current_user: CurrentUser = Depends(verify_token)):
    """获取文档元数据和 chunk 列表。"""
    if not await has_permission(current_user, document_id, "read"):
        raise HTTPException(status_code=404, detail="文档不存在")
    payload = await document_service.get_document_chunks(document_id)
    if not payload:
        raise HTTPException(status_code=404, detail="文档不存在")
    return payload


@router.get("/documents/{document_id}/chunks/by-key/{chunk_key}")
async def get_document_chunk_by_key(
    document_id: str,
    chunk_key: str,
    current_user: CurrentUser = Depends(verify_token),
):
    """按 stable chunk_key 获取单个源 chunk 完整内容。"""
    if not await has_permission(current_user, document_id, "read"):
        raise HTTPException(status_code=404, detail="文档不存在")
    chunk = await document_service.get_document_chunk_by_key(document_id, chunk_key)
    if not chunk:
        raise HTTPException(status_code=404, detail="当前索引或解析产物中未找到该 chunk")
    return chunk


@router.get("/documents/{document_id}/related")
async def get_related_documents(document_id: str, current_user: CurrentUser = Depends(verify_token)):
    """返回同 entity 且用户可见的相关文档列表。"""
    if not await has_permission(current_user, document_id, "read"):
        raise HTTPException(status_code=404, detail="文档不存在")
    allowed = await get_allowed_document_ids(current_user)
    return await document_service.list_related_documents(document_id, allowed)


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: str,
    body: UpdateDocumentRequest,
    current_user: CurrentUser = Depends(verify_token),
):
    """更新文档 entity_name（需 write 权限）。"""
    await _require_write(current_user, document_id)

    # Canonicalize target entity
    target = normalize_entity_name(body.entity_name)
    if not target:
        raise HTTPException(status_code=400, detail="entity_name 不能为空")
    async with get_db() as db:
        canonical_target = await canonicalize_entity_name(target, db)
    if not await can_write_entity(current_user, canonical_target):
        raise HTTPException(status_code=403, detail=f"无权移动到实体 '{canonical_target}'")

    ok = await document_service.update_entity_name(document_id, canonical_target)
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
    current_user: CurrentUser = Depends(verify_token),
):
    """启动后台导入任务（需 write 权限）。"""
    await _require_write(current_user, document_id)
    claimed = await document_service.claim_document_for_processing(document_id)
    if not claimed:
        doc = await document_service.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")
        if doc["status"] == "failed":
            raise HTTPException(status_code=400, detail="文档状态为 failed，请使用 /retry 端点重试")
        raise HTTPException(status_code=400, detail=f"文档状态为 {doc['status']}，无法处理")

    try:
        job = await document_service.create_document_job(
            document_id,
            job_type=document_service.DOCUMENT_JOB_TYPE_INGESTION,
            created_by=current_user.user_id,
            message="queued",
        )
    except Exception as exc:
        await document_service.update_document_status(document_id, "uploaded")
        raise HTTPException(status_code=500, detail="任务创建失败，请稍后重试") from exc

    background_tasks.add_task(document_service.process_document, document_id, job["job_id"])
    return {"ok": True, "message": "Document processing started", "job_id": job["job_id"]}


MAX_RETRIES = 3


@router.post("/documents/{document_id}/retry")
async def retry_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(verify_token),
):
    """重试 failed 状态的通用文档（需 write 权限）。"""
    await _require_write(current_user, document_id)
    doc = await document_service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc["status"] != "failed":
        raise HTTPException(status_code=400, detail=f"文档状态为 {doc['status']}，无法 retry")

    retry_count = doc.get("retry_count", 0) or 0
    if retry_count >= MAX_RETRIES:
        raise HTTPException(status_code=429, detail=f"重试次数已达上限({MAX_RETRIES})")

    job = await document_service.create_document_job(
        document_id,
        job_type=document_service.DOCUMENT_JOB_TYPE_RETRY,
        created_by=current_user.user_id,
        attempt_count=retry_count + 1,
        message="queued",
    )

    # 重试前清理 Milvus 中可能残留的旧向量——失败则阻断，避免重复向量
    try:
        await document_service.mark_document_job_retry_cleanup(job["job_id"])
        await asyncio.to_thread(document_service._sync_delete_from_milvus, document_id)
    except Exception as exc:
        from app.errors import classify_error
        code = classify_error(exc)
        await document_service.append_error_event(document_id, "pre_retry_cleanup", code.value, str(exc))
        await document_service.mark_document_job_failed(
            job["job_id"],
            error_code=code.value,
            error_detail=str(exc),
            message="pre_retry_cleanup",
        )
        raise HTTPException(status_code=503, detail="Milvus 向量清理失败，请稍后重试")

    await document_service.update_document_status(
        document_id, "processing",
        retry_count=retry_count + 1,
        error_msg="", error_code="",
    )
    background_tasks.add_task(document_service.process_document, document_id, job["job_id"])
    return {"ok": True, "message": "Document retry started", "job_id": job["job_id"]}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, response: Response, current_user: CurrentUser = Depends(verify_token)):
    """删除通用文档（需 write 权限）。"""
    await _require_write(current_user, document_id)
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
    # 只在完全删除后确认
    return {"ok": True, "status": "deleted"}


@router.post("/documents/{document_id}/repair-delete")
async def repair_delete(document_id: str, current_user: CurrentUser = Depends(verify_token)):
    """修复删除（需 write 权限）。"""
    await _require_write(current_user, document_id)
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


async def _verify_asset_access(document_id: str, token: str | None, authorization: str | None) -> CurrentUser:
    """Asset 接口鉴权：支持 query param token 或 Bearer header。返回 CurrentUser。"""
    raw = token or ""
    if not raw and authorization:
        raw = authorization.removeprefix("Bearer ").strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Missing token")

    from app.core.auth import lookup_user
    user = await lookup_user(raw)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    from app.core.auth import has_permission
    if not await has_permission(user, document_id, "read"):
        raise HTTPException(status_code=403, detail="Access denied")
    return user


@router.get("/documents/{document_id}/assets/{asset_path:path}")
async def get_document_asset(
    document_id: str,
    asset_path: str,
    token: str | None = None,
    authorization: str | None = Header(None),
):
    """安全提供文档解析产物（图片等）。需对该文档有 read 权限。"""
    await _verify_asset_access(document_id, token, authorization)

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
