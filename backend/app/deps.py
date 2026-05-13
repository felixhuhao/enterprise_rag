"""
依赖注入模块 — API 鉴权

提供 FastAPI 依赖项 verify_token，用于对所有 API 接口进行
简单的 Bearer Token 身份验证。令牌值从 config.py 的 settings 中读取。
"""

import hmac

from fastapi import Header, HTTPException

from app.config import settings


async def verify_token(authorization: str = Header(...)):
    """
    验证请求头中的 Bearer Token

    从 Authorization 请求头中提取令牌，与配置中的 API_TOKEN 比对。
    使用 hmac.compare_digest 做常量时间比较，防止时序攻击。
    若不匹配则返回 401 未授权错误。

    参数:
        authorization: HTTP 请求头中的 Authorization 字段值（自动注入）

    异常:
        HTTPException: 令牌无效时抛出 401 状态码
    """
    expected = f"Bearer {settings.API_TOKEN}"
    if not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Invalid token")
