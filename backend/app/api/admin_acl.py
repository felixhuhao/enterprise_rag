"""Admin ACL audit — GET /admin/acl/documents."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.deps import verify_token

router = APIRouter()


@router.get("/admin/acl/documents")
async def get_acl_audit(current_user: CurrentUser = Depends(verify_token)):
    """返回所有文档的 ACL 分配情况。admin only。"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看权限审计")

    async with get_db() as db:
        # users
        async with db.execute(
            "SELECT user_id, username, role FROM users ORDER BY username"
        ) as cursor:
            users = [dict(r) for r in await cursor.fetchall()]

        # documents with LEFT JOIN permissions
        async with db.execute(
            "SELECT d.document_id, d.filename, d.entity_name, d.status, "
            "d.cleanup_status, "
            "a.user_id AS acl_user_id, a.permission AS acl_permission, "
            "u.username AS acl_username, u.role AS acl_role "
            "FROM general_documents d "
            "LEFT JOIN document_acl a ON d.document_id = a.document_id "
            "LEFT JOIN users u ON a.user_id = u.user_id "
            "ORDER BY d.created_at DESC, a.permission"
        ) as cursor:
            rows = await cursor.fetchall()

    # group by document
    docs_map: dict[str, dict] = {}
    for r in rows:
        did = r["document_id"]
        if did not in docs_map:
            docs_map[did] = {
                "document_id": did,
                "filename": r["filename"],
                "entity_name": r["entity_name"],
                "status": r["status"],
                "cleanup_status": r["cleanup_status"],
                "permissions": [],
            }
        if r["acl_user_id"]:
            docs_map[did]["permissions"].append({
                "user_id": r["acl_user_id"],
                "username": r["acl_username"],
                "role": r["acl_role"],
                "permission": r["acl_permission"],
            })

    return {"users": users, "documents": list(docs_map.values())}
