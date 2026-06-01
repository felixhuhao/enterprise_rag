"""Admin structured tag governance APIs."""

from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.core.auth import CurrentUser, require_admin
from app.core.database import get_db
from app.deps import verify_token
from app.rag.chunking.enrichment import MAX_KEYWORDS, build_search_text, extract_keywords, extract_structured_tags
from app.rag.chunking.structured_tag_registry import (
    BUILTIN_STRUCTURED_TAGS,
    StructuredTagDefinition,
    apply_structured_tag_override,
    get_builtin_structured_tag_definition,
    get_structured_tag_definition,
    invalidate_structured_tag_overrides,
)

router = APIRouter()


class StructuredTagUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = Field(None, max_length=400)
    enabled: bool | None = None
    ui_visible: bool | None = None


class StructuredTagPreviewRequest(BaseModel):
    text: str | None = Field(None, max_length=20000)
    section_title: str = Field("", max_length=300)
    document_id: str | None = Field(None, max_length=120)
    profile: str = "enterprise_policy"
    max_chunks: int = Field(20, ge=1, le=100)


_TAG_EVIDENCE_TERMS = {
    "amount_threshold": ("超过", "以下", "以上", "以内", "不低于", "不超过", "元", "万"),
    "approval_rule": ("审批", "批准", "签字", "审核", "复核"),
    "training_budget": ("培训", "预算", "费用", "报销", "审批"),
    "deadline_rule": ("提交", "报告", "响应", "处理", "申请", "工作日", "自然日", "小时"),
    "security_incident_rule": ("安全事件", "信息安全", "数据泄露", "设备丢失", "响应", "报告"),
    "payment_rule": ("付款", "支付"),
    "reimbursement_rule": ("报销", "费用"),
    "procurement_rule": ("采购", "供应商"),
    "budget_rule": ("预算", "金额"),
}


def _clean_optional_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if field == "label" and not cleaned:
        raise HTTPException(status_code=400, detail=f"{field} cannot be empty")
    return cleaned


def _definition_or_404(tag_key: str) -> StructuredTagDefinition:
    definition = get_builtin_structured_tag_definition(tag_key)
    if not definition:
        raise HTTPException(status_code=404, detail="Structured tag not found")
    return definition


def _tag_record(definition: StructuredTagDefinition, override: dict | None) -> dict:
    row = override or {}
    effective = apply_structured_tag_override(definition, row)
    return {
        "tag_key": definition.tag_key,
        "label": effective.label,
        "default_label": definition.label,
        "description": effective.description,
        "default_description": definition.description,
        "priority": definition.priority,
        "scope": definition.scope,
        "profile": definition.profile,
        "enabled": effective.enabled,
        "default_enabled": definition.enabled,
        "ui_visible": effective.ui_visible,
        "default_ui_visible": definition.ui_visible,
        "overridden": bool(override),
        "updated_at": row.get("updated_at", ""),
    }


def _preserve_or_override(
    provided: object,
    current: object,
    default: object,
    *,
    was_provided: bool,
) -> object | None:
    if was_provided:
        return provided
    return None if current == default else current


async def _override_rows() -> dict[str, dict]:
    async with get_db() as db:
        async with db.execute(
            """SELECT tag_key, label, description, enabled, ui_visible, updated_at
               FROM structured_tag_overrides"""
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]
    return {row["tag_key"]: row for row in rows}


async def _override_row(tag_key: str) -> dict | None:
    async with get_db() as db:
        async with db.execute(
            """SELECT tag_key, label, description, enabled, ui_visible, updated_at
               FROM structured_tag_overrides
               WHERE tag_key = ?""",
            (tag_key,),
        ) as cursor:
            row = await cursor.fetchone()
    return dict(row) if row else None


@router.get("/admin/structured-tags")
async def list_structured_tags(current_user: CurrentUser = Depends(verify_token)):
    require_admin(current_user)
    overrides = await _override_rows()
    records = [_tag_record(definition, overrides.get(definition.tag_key)) for definition in BUILTIN_STRUCTURED_TAGS]
    return {"records": records, "total": len(records)}


@router.get("/admin/structured-tags/metrics")
async def get_structured_tag_metrics(current_user: CurrentUser = Depends(verify_token)):
    require_admin(current_user)
    return await asyncio.to_thread(_build_tag_metrics)


@router.post("/admin/structured-tags/preview")
async def preview_structured_tags(
    body: StructuredTagPreviewRequest,
    current_user: CurrentUser = Depends(verify_token),
):
    require_admin(current_user)
    chunks = _preview_chunks(body)
    if not chunks:
        raise HTTPException(status_code=400, detail="text or document_id is required")
    items = [_preview_item(chunk, body.profile) for chunk in chunks[: body.max_chunks]]
    matched = [item for item in items if item["structured_tags"]]
    tag_counter = Counter(tag["tag_key"] for item in items for tag in item["structured_tags"])
    return {
        "source": "document" if body.document_id else "text",
        "document_id": body.document_id or "",
        "profile": body.profile,
        "summary": {
            "chunk_count": len(items),
            "matched_chunks": len(matched),
            "tag_count": sum(tag_counter.values()),
        },
        "tag_counts": _tag_count_rows(tag_counter, {}),
        "items": items,
    }


@router.patch("/admin/structured-tags/{tag_key}")
async def update_structured_tag(
    tag_key: str,
    body: StructuredTagUpdate,
    current_user: CurrentUser = Depends(verify_token),
):
    require_admin(current_user)
    definition = _definition_or_404(tag_key)
    if body.label is None and body.description is None and body.enabled is None and body.ui_visible is None:
        raise HTTPException(status_code=400, detail="No editable fields provided")

    before = _tag_record(definition, await _override_row(tag_key))
    label = _clean_optional_text(body.label, "label")
    description = _clean_optional_text(body.description, "description")

    values = {
        "label": _preserve_or_override(label, before["label"], definition.label, was_provided=body.label is not None),
        "description": _preserve_or_override(
            description,
            before["description"],
            definition.description,
            was_provided=body.description is not None,
        ),
        "enabled": _preserve_or_override(
            int(body.enabled) if body.enabled is not None else None,
            int(before["enabled"]),
            int(definition.enabled),
            was_provided=body.enabled is not None,
        ),
        "ui_visible": _preserve_or_override(
            int(body.ui_visible) if body.ui_visible is not None else None,
            int(before["ui_visible"]),
            int(definition.ui_visible),
            was_provided=body.ui_visible is not None,
        ),
    }

    async with get_db() as db:
        await db.execute(
            """INSERT INTO structured_tag_overrides
               (tag_key, label, description, enabled, ui_visible, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(tag_key) DO UPDATE SET
                   label = excluded.label,
                   description = excluded.description,
                   enabled = excluded.enabled,
                   ui_visible = excluded.ui_visible,
                   updated_at = CURRENT_TIMESTAMP""",
            (tag_key, values["label"], values["description"], values["enabled"], values["ui_visible"]),
        )
        await db.commit()

    invalidate_structured_tag_overrides()
    after = _tag_record(definition, await _override_row(tag_key))
    return {"record": after, "reindex_required": before["enabled"] != after["enabled"]}


@router.post("/admin/structured-tags/{tag_key}/reset")
async def reset_structured_tag(
    tag_key: str,
    current_user: CurrentUser = Depends(verify_token),
):
    require_admin(current_user)
    definition = _definition_or_404(tag_key)
    before = _tag_record(definition, await _override_row(tag_key))
    async with get_db() as db:
        cursor = await db.execute("DELETE FROM structured_tag_overrides WHERE tag_key = ?", (tag_key,))
        await db.commit()
    if not cursor.rowcount:
        raise HTTPException(status_code=404, detail="Structured tag override not found")
    invalidate_structured_tag_overrides()
    after = _tag_record(definition, None)
    return {"record": after, "reindex_required": before["enabled"] != after["enabled"]}


def _build_tag_metrics() -> dict:
    chunk_count = 0
    zero_tag_chunks = 0
    too_many_keywords_chunks = 0
    documents: set[str] = set()
    tag_chunks: Counter[str] = Counter()
    tag_documents: dict[str, set[str]] = defaultdict(set)
    tag_source_types: Counter[tuple[str, str]] = Counter()
    keyword_counter: Counter[str] = Counter()

    for document_id, chunk in _iter_parsed_chunks():
        documents.add(document_id)
        chunk_count += 1
        tags = _string_list(chunk.get("structured_tags"))
        keywords = _string_list(chunk.get("keywords"))
        if not tags:
            zero_tag_chunks += 1
        if len(keywords) > MAX_KEYWORDS:
            too_many_keywords_chunks += 1
        source_type = str(chunk.get("source_type") or "unknown")
        for keyword in keywords:
            keyword_counter[keyword] += 1
        for tag_key in tags:
            tag_chunks[tag_key] += 1
            tag_documents[tag_key].add(document_id)
            tag_source_types[(tag_key, source_type)] += 1

    return {
        "summary": {
            "document_count": len(documents),
            "chunk_count": chunk_count,
            "zero_tag_chunks": zero_tag_chunks,
            "too_many_keywords_chunks": too_many_keywords_chunks,
        },
        "top_tags": _tag_count_rows(tag_chunks, tag_documents),
        "top_keywords": [{"keyword": key, "chunks": count} for key, count in keyword_counter.most_common(20)],
        "by_source_type": [
            {"tag_key": tag_key, "label": _tag_label(tag_key), "source_type": source_type, "chunks": count}
            for (tag_key, source_type), count in sorted(tag_source_types.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def _preview_chunks(body: StructuredTagPreviewRequest) -> list[dict]:
    if body.document_id:
        chunks_path = Path(settings.GENERAL_PARSED_DIR) / body.document_id / "chunks.json"
        if not chunks_path.exists():
            raise HTTPException(status_code=404, detail="Document chunks artifact not found")
        try:
            rows = json.loads(chunks_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read chunks artifact: {exc}") from exc
        if not isinstance(rows, list):
            raise HTTPException(status_code=500, detail="Invalid chunks artifact")
        return [row for row in rows if isinstance(row, dict)]

    text = (body.text or "").strip()
    if not text:
        return []
    return [{"content": text, "section_title": body.section_title, "source_type": "text"}]


def _preview_item(chunk: dict, profile: str) -> dict:
    content = str(chunk.get("content") or "")
    section_title = str(chunk.get("section_title") or "")
    tags = extract_structured_tags(content, section_title, profile=profile)
    keywords = extract_keywords(content, section_title, profile=profile)
    search_text = build_search_text(
        {
            **chunk,
            "keywords": keywords,
            "structured_tags": tags,
        },
        profile=profile,
    )
    return {
        "chunk_key": str(chunk.get("chunk_key") or ""),
        "section_title": section_title,
        "source_type": str(chunk.get("source_type") or "text"),
        "structured_tags": [{"tag_key": tag_key, "label": _tag_label(tag_key)} for tag_key in tags],
        "keywords": keywords,
        "evidence": [{"tag_key": tag_key, "snippet": _evidence_snippet(tag_key, f"{section_title}\n{content}")} for tag_key in tags],
        "search_text_length": len(search_text),
        "search_text_preview": search_text[:500],
    }


def _iter_parsed_chunks():
    parsed_root = Path(settings.GENERAL_PARSED_DIR)
    if not parsed_root.exists():
        return
    for chunks_path in parsed_root.glob("*/chunks.json"):
        try:
            rows = json.loads(chunks_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rows, list):
            continue
        document_id = chunks_path.parent.name
        for row in rows:
            if isinstance(row, dict):
                yield document_id, row


def _tag_count_rows(tag_counter: Counter[str], tag_documents: dict[str, set[str]]) -> list[dict]:
    rows = []
    for tag_key, chunks in tag_counter.most_common():
        rows.append({
            "tag_key": tag_key,
            "label": _tag_label(tag_key),
            "chunks": chunks,
            "documents": len(tag_documents.get(tag_key, set())),
        })
    return rows


def _tag_label(tag_key: str) -> str:
    definition = get_structured_tag_definition(tag_key)
    return definition.label if definition else tag_key


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _evidence_snippet(tag_key: str, text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    for term in _TAG_EVIDENCE_TERMS.get(tag_key, ()):
        index = cleaned.find(term)
        if index >= 0:
            start = max(0, index - 40)
            end = min(len(cleaned), index + len(term) + 80)
            return cleaned[start:end]
    return cleaned[:120]
