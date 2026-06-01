"""Admin entity alias CRUD APIs."""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser, require_admin
from app.core.database import get_db
from app.deps import verify_token
from app.rag.query.entity_cache import get_known_entities, invalidate

router = APIRouter()


class EntityAliasCreate(BaseModel):
    alias: str = Field(..., min_length=1, max_length=120)
    canonical_entity: str = Field(..., min_length=1, max_length=200)
    source: str = "admin"


class EntityAliasBatchItem(BaseModel):
    alias: str = Field(..., min_length=1, max_length=120)
    canonical_entity: str = Field(..., min_length=1, max_length=200)
    source: str = "admin"


def _clean_source(source: str) -> str:
    return source if source in {"manual", "admin"} else "admin"


def _clean_required(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field} cannot be empty")
    return cleaned


def _validate_canonical(canonical: str):
    if canonical not in get_known_entities():
        raise HTTPException(status_code=400, detail=f"Unknown canonical entity: {canonical}")


@router.get("/admin/entity-aliases")
async def list_entity_aliases(
    page: int = 1,
    page_size: int = 100,
    current_user: CurrentUser = Depends(verify_token),
):
    require_admin(current_user)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 500)
    offset = (page - 1) * page_size
    async with get_db() as db:
        async with db.execute(
            """SELECT id, alias, canonical_entity, source, created_at
               FROM entity_aliases
               ORDER BY alias ASC, canonical_entity ASC
               LIMIT ? OFFSET ?""",
            (page_size, offset),
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]
        async with db.execute("SELECT COUNT(*) as total FROM entity_aliases") as cursor:
            total = (await cursor.fetchone())["total"]
    return {"records": rows, "total": total, "page": page, "page_size": page_size}


@router.get("/admin/entity-aliases/lookup")
async def lookup_entity_alias(
    alias: str,
    current_user: CurrentUser = Depends(verify_token),
):
    require_admin(current_user)
    async with get_db() as db:
        async with db.execute(
            """SELECT id, alias, canonical_entity, source, created_at
               FROM entity_aliases
               WHERE alias = ?
               ORDER BY canonical_entity ASC""",
            (alias.strip(),),
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]
    return {"alias": alias, "records": rows}


@router.post("/admin/entity-aliases")
async def create_entity_alias(
    body: EntityAliasCreate,
    current_user: CurrentUser = Depends(verify_token),
):
    require_admin(current_user)
    alias = _clean_required(body.alias, "alias")
    canonical = _clean_required(body.canonical_entity, "canonical_entity")
    _validate_canonical(canonical)
    try:
        async with get_db() as db:
            cursor = await db.execute(
                """INSERT INTO entity_aliases (alias, canonical_entity, source)
                   VALUES (?, ?, ?)""",
                (alias, canonical, _clean_source(body.source)),
            )
            await db.commit()
            alias_id = cursor.lastrowid
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="Alias mapping already exists") from None
    invalidate()
    return {
        "id": alias_id,
        "alias": alias,
        "canonical_entity": canonical,
        "source": _clean_source(body.source),
    }


@router.post("/admin/entity-aliases/batch")
async def batch_create_entity_aliases(
    body: list[EntityAliasBatchItem],
    current_user: CurrentUser = Depends(verify_token),
):
    require_admin(current_user)
    known = get_known_entities()
    created = 0
    skipped = 0
    errors: list[dict] = []
    async with get_db() as db:
        for item in body:
            alias = item.alias.strip()
            canonical = item.canonical_entity.strip()
            if not alias or not canonical:
                errors.append({"alias": alias, "canonical_entity": canonical, "error": "empty_value"})
                continue
            if canonical not in known:
                errors.append({"alias": alias, "canonical_entity": canonical, "error": "unknown_canonical"})
                continue
            try:
                cursor = await db.execute(
                    """INSERT OR IGNORE INTO entity_aliases (alias, canonical_entity, source)
                       VALUES (?, ?, ?)""",
                    (alias, canonical, _clean_source(item.source)),
                )
            except aiosqlite.Error as exc:
                errors.append({"alias": alias, "canonical_entity": canonical, "error": str(exc)})
                continue
            if cursor.rowcount:
                created += 1
            else:
                skipped += 1
        await db.commit()
    if created:
        invalidate()
    return {"created": created, "skipped": skipped, "errors": errors}


@router.delete("/admin/entity-aliases/{alias_id}")
async def delete_entity_alias(
    alias_id: int,
    current_user: CurrentUser = Depends(verify_token),
):
    require_admin(current_user)
    async with get_db() as db:
        cursor = await db.execute("DELETE FROM entity_aliases WHERE id = ?", (alias_id,))
        await db.commit()
    if not cursor.rowcount:
        raise HTTPException(status_code=404, detail="Alias mapping not found")
    invalidate()
    return {"ok": True}
