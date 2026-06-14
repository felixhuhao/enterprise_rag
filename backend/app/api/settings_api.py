"""
设置 API 端点模块

提供运行时配置的读取和更新接口。

端点：
- GET /settings: 获取所有设置项
- PUT /settings: 批量更新设置项
- POST /settings/token: 已停用 (410)
"""

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import CurrentUser
from app.deps import verify_token
from app.core.runtime_settings import runtime_settings
from app.models.schemas import SettingsUpdate

router = APIRouter()


@router.get("/settings")
async def get_settings(current_user: CurrentUser = Depends(verify_token)):
    return await runtime_settings.get_all()


@router.put("/settings")
async def update_settings(
    request: SettingsUpdate,
    current_user: CurrentUser = Depends(verify_token),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可修改设置")
    if not request.settings:
        raise HTTPException(status_code=400, detail="settings 不能为空")
    await runtime_settings.update_batch(request.settings)
    return await runtime_settings.get_all()


@router.post("/settings/token", status_code=410)
async def update_token():
    """Deprecated: token rotation retired. Bootstrap token is env-only."""
    raise HTTPException(
        status_code=410,
        detail="Token 轮换已停用。引导 Token 仅通过 .env API_TOKEN 管理。",
    )
