"""Admin user management and entity ACL API — admin-only."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.auth import (
    CurrentUser,
    delete_session,
    get_bootstrap_admin_id,
    grant_entity,
    hash_password,
    revoke_entity,
    user_entities,
)
from app.core.database import get_db
from app.core.entity import normalize_entity_name
from app.deps import require_admin_user

router = APIRouter()

MIN_PASSWORD_LENGTH = 8

# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"

    @field_validator("username")
    @classmethod
    def username_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("username 不能为空")
        return v.strip()

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"密码至少 {MIN_PASSWORD_LENGTH} 位")
        if len(v.encode("utf-8")) > 72:
            raise ValueError("密码超过 72 字节")
        return v

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        if v not in ("user", "admin"):
            raise ValueError("role 必须为 'user' 或 'admin'")
        return v


class ResetPasswordRequest(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"密码至少 {MIN_PASSWORD_LENGTH} 位")
        if len(v.encode("utf-8")) > 72:
            raise ValueError("密码超过 72 字节")
        return v


class GrantRequest(BaseModel):
    entity_name: str
    user_id: str
    permission: str

    @field_validator("permission")
    @classmethod
    def permission_valid(cls, v: str) -> str:
        if v not in ("read", "write"):
            raise ValueError("permission 必须为 'read' 或 'write'")
        return v


class RevokeRequest(BaseModel):
    entity_name: str
    user_id: str


# --------------------------------------------------------------------------- #
# User CRUD
# --------------------------------------------------------------------------- #


@router.post("/admin/users")
async def create_user(
    body: CreateUserRequest,
    current_user: CurrentUser = Depends(require_admin_user),
):
    """Create a new user. Returns 409 on duplicate username."""
    pw_hash = hash_password(body.password)
    now = datetime.now(timezone.utc).isoformat()
    user_id = f"u_{body.username.lower()}"

    async with get_db() as db:
        # Check username uniqueness
        async with db.execute(
            "SELECT 1 FROM users WHERE username = ?", (body.username,)
        ) as cursor:
            if await cursor.fetchone():
                raise HTTPException(status_code=409, detail="用户名已存在")

        try:
            await db.execute(
                "INSERT INTO users (user_id, username, password_hash, created_at, role) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, body.username, pw_hash, now, body.role),
            )
            await db.commit()
        except Exception:
            raise HTTPException(status_code=409, detail="用户名已存在")

    return {"user_id": user_id, "username": body.username, "role": body.role}


@router.get("/admin/users")
async def list_users(
    current_user: CurrentUser = Depends(require_admin_user),
):
    """List all users."""
    async with get_db() as db:
        async with db.execute(
            "SELECT user_id, username, role, created_at FROM users ORDER BY username"
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {"user_id": r["user_id"], "username": r["username"], "role": r["role"], "created_at": r["created_at"]}
        for r in rows
    ]


@router.post("/admin/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    current_user: CurrentUser = Depends(require_admin_user),
):
    """Set a new password and delete all existing sessions for the user."""
    pw_hash = hash_password(body.password)

    async with get_db() as db:
        async with db.execute(
            "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            if not await cursor.fetchone():
                raise HTTPException(status_code=404, detail="用户不存在")

        await db.execute(
            "UPDATE users SET password_hash = ? WHERE user_id = ?",
            (pw_hash, user_id),
        )
        await db.execute(
            "DELETE FROM auth_sessions WHERE user_id = ?", (user_id,)
        )
        await db.commit()

    return {"ok": True}


@router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: str,
    current_user: CurrentUser = Depends(require_admin_user),
):
    """Delete a user, their sessions, and entity grants.

    Rejects deleting the last admin and the bootstrap admin.
    """
    bootstrap_id = await get_bootstrap_admin_id()
    if user_id == bootstrap_id:
        raise HTTPException(status_code=409, detail="无法删除引导管理员账户")

    async with get_db() as db:
        async with db.execute(
            "SELECT role FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")

        if row["role"] == "admin":
            async with db.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE role = 'admin'"
            ) as cursor:
                admin_count = (await cursor.fetchone())["cnt"]
            if admin_count <= 1:
                raise HTTPException(status_code=409, detail="无法删除最后一个管理员")

        await db.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM entity_acl WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await db.commit()

    return {"ok": True}


# --------------------------------------------------------------------------- #
# Entity ACL management
# --------------------------------------------------------------------------- #


@router.get("/admin/entities")
async def list_entities(
    current_user: CurrentUser = Depends(require_admin_user),
):
    """List known non-blank entity names (documents ∪ entity_acl)."""
    async with get_db() as db:
        async with db.execute(
            "SELECT DISTINCT entity_name FROM general_documents WHERE entity_name != '' "
            "UNION SELECT DISTINCT entity_name FROM entity_acl ORDER BY entity_name"
        ) as cursor:
            rows = await cursor.fetchall()
    return [r["entity_name"] for r in rows]


@router.post("/admin/acl/grant")
async def grant_access(
    body: GrantRequest,
    current_user: CurrentUser = Depends(require_admin_user),
):
    """Grant entity access to a user."""
    ok = await grant_entity(body.entity_name, body.user_id, body.permission)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="授权失败，请检查 entity_name、user_id 和 permission",
        )
    return {"ok": True}


@router.post("/admin/acl/revoke")
async def revoke_access(
    body: RevokeRequest,
    current_user: CurrentUser = Depends(require_admin_user),
):
    """Revoke entity access from a user."""
    await revoke_entity(body.entity_name, body.user_id)
    return {"ok": True}


@router.get("/admin/acl/entities")
async def get_entity_acl_overview(
    current_user: CurrentUser = Depends(require_admin_user),
):
    """Entity-level ACL audit: entities × grants."""
    async with get_db() as db:
        async with db.execute(
            "SELECT ea.entity_name, ea.user_id, ea.permission, u.username, u.role "
            "FROM entity_acl ea JOIN users u ON ea.user_id = u.user_id "
            "ORDER BY ea.entity_name, u.username"
        ) as cursor:
            rows = await cursor.fetchall()

        async with db.execute(
            "SELECT entity_name, COUNT(*) as doc_count, "
            "SUM(CASE WHEN uploaded_by != '' THEN 1 ELSE 0 END) as has_uploader "
            "FROM general_documents WHERE entity_name != '' "
            "GROUP BY entity_name ORDER BY entity_name"
        ) as cursor:
            doc_rows = await cursor.fetchall()

    grants_map: dict[str, list] = {}
    for r in rows:
        grants_map.setdefault(r["entity_name"], []).append({
            "user_id": r["user_id"],
            "username": r["username"],
            "role": r["role"],
            "permission": r["permission"],
        })

    entities = []
    for dr in doc_rows:
        ent = dr["entity_name"]
        entities.append({
            "entity_name": ent,
            "document_count": dr["doc_count"],
            "grants": grants_map.get(ent, []),
        })

    # Include entities that have grants but no documents
    for ent, grants in grants_map.items():
        if not any(e["entity_name"] == ent for e in entities):
            entities.append({
                "entity_name": ent,
                "document_count": 0,
                "grants": grants,
            })

    return {"entities": entities}
