"""Auth API — login / logout."""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, field_validator

from app.core.auth import create_session, delete_session, verify_password
from app.core.database import get_db

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username", "password")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("不能为空")
        return v


@router.post("/auth/login")
async def login(body: LoginRequest):
    """Login with username/password. Returns ``{token, user, expires_at}``."""
    async with get_db() as db:
        async with db.execute(
            "SELECT user_id, username, role, password_hash FROM users WHERE username = ?",
            (body.username.strip(),),
        ) as cursor:
            row = await cursor.fetchone()

    if not row or not row["password_hash"]:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    raw_token, expires_at = await create_session(row["user_id"])
    return {
        "token": raw_token,
        "user": {
            "user_id": row["user_id"],
            "username": row["username"],
            "role": row["role"],
        },
        "expires_at": expires_at,
    }


@router.post("/auth/logout")
async def logout(authorization: str = Header(default="")):
    """Delete the current session. Always returns 200 (idempotent)."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token:
        await delete_session(token)
    return {"ok": True}
