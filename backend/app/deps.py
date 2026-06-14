"""
依赖注入模块 — API 鉴权

提供 FastAPI 依赖项 verify_token，基于 Bearer Token 查找用户。
admin token 兼容旧的 API_TOKEN 配置。
"""

from fastapi import Depends, Header, HTTPException

from app.core.auth import CurrentUser, lookup_user, require_admin


async def verify_token(authorization: str = Header(...)) -> CurrentUser:
    """
    验证请求头中的 Bearer Token，返回 CurrentUser。

    参数:
        authorization: HTTP 请求头中的 Authorization 字段值（自动注入）

    异常:
        HTTPException: 令牌无效时抛出 401
    """
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    user = await lookup_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    return user


async def require_admin_user(
    current_user: CurrentUser = Depends(verify_token),
) -> CurrentUser:
    """Verify token AND require admin role. Use as Depends on admin routes."""
    require_admin(current_user)
    return current_user
