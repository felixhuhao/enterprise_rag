"""Admin structured tag governance APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.deps import verify_token
from app.rag.chunking.structured_tag_registry import (
    BUILTIN_STRUCTURED_TAGS,
    StructuredTagDefinition,
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


def _require_admin(user: CurrentUser):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员")


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
    effective = get_structured_tag_definition(definition.tag_key) or definition
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
    _require_admin(current_user)
    overrides = await _override_rows()
    records = [_tag_record(definition, overrides.get(definition.tag_key)) for definition in BUILTIN_STRUCTURED_TAGS]
    return {"records": records, "total": len(records)}


@router.patch("/admin/structured-tags/{tag_key}")
async def update_structured_tag(
    tag_key: str,
    body: StructuredTagUpdate,
    current_user: CurrentUser = Depends(verify_token),
):
    _require_admin(current_user)
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
    _require_admin(current_user)
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
