"""Authentication & authorization — token → user lookup, document ACL."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from app.core.database import get_db


@dataclass
class CurrentUser:
    user_id: str
    username: str
    role: str  # 'user' | 'admin'


def require_admin(user: CurrentUser) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员")


async def lookup_user(token: str) -> CurrentUser | None:
    if not token:
        return None
    async with get_db() as db:
        async with db.execute(
            "SELECT user_id, username, role FROM users WHERE api_token = ?", (token,)
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None
    return CurrentUser(user_id=row["user_id"], username=row["username"], role=row["role"])


async def get_allowed_document_ids(user: CurrentUser) -> list[str] | None:
    """返回用户可读的 document_id 列表。admin → None（不限制）。"""
    if user.role == "admin":
        return None

    async with get_db() as db:
        async with db.execute(
            "SELECT document_id FROM document_acl WHERE user_id = ? AND permission IN ('read', 'owner')",
            (user.user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [r["document_id"] for r in rows]


async def has_permission(user: CurrentUser, document_id: str, min_permission: str) -> bool:
    """检查用户对指定文档的最小权限。admin 全部通过。"""
    if user.role == "admin":
        return True

    if min_permission == "read":
        # read 或 owner 均可
        sql = "SELECT 1 FROM document_acl WHERE document_id = ? AND user_id = ? AND permission IN ('read', 'owner')"
        params = (document_id, user.user_id)
    else:
        sql = "SELECT 1 FROM document_acl WHERE document_id = ? AND user_id = ? AND permission = 'owner'"
        params = (document_id, user.user_id)

    async with get_db() as db:
        async with db.execute(sql, params) as cursor:
            row = await cursor.fetchone()
    return row is not None


async def grant_permission(document_id: str, user_id: str, permission: str) -> bool:
    """授予文档权限。校验 target user 存在、permission 合法。返回是否成功。"""
    if permission not in ("read", "owner"):
        return False

    async with get_db() as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            if not await cursor.fetchone():
                return False
        async with db.execute("SELECT 1 FROM general_documents WHERE document_id = ?", (document_id,)) as cursor:
            if not await cursor.fetchone():
                return False

        try:
            await db.execute(
                "INSERT OR REPLACE INTO document_acl (document_id, user_id, permission) VALUES (?, ?, ?)",
                (document_id, user_id, permission),
            )
            await db.commit()
        except Exception:
            return False
    return True


async def remove_document_acl(document_id: str):
    """删除文档的所有 ACL 记录（级联删除时调用）。"""
    async with get_db() as db:
        await db.execute("DELETE FROM document_acl WHERE document_id = ?", (document_id,))
        await db.commit()
