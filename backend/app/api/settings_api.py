"""
设置 API 端点模块

提供运行时配置的读取和更新接口。

端点：
- GET /settings: 获取所有设置项
- PUT /settings: 批量更新设置项
- POST /settings/token: 更新 API Token
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import CurrentUser
from app.deps import verify_token
from app.config import settings
from app.core.runtime_settings import runtime_settings
from app.models.schemas import SettingsUpdate, TokenUpdate

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


@router.post("/settings/token")
async def update_token(
    request: TokenUpdate,
    current_user: CurrentUser = Depends(verify_token),
):
    """
    更新 API Token

    更新当前进程的 API Token，立即生效。同时写入 .env 文件持久化。

    参数:
        request: Token 更新请求体 { token: "新 token" }
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可修改 Token")
    new_token = request.token.strip()
    if not new_token:
        raise HTTPException(status_code=400, detail="Token 不能为空")

    # 更新进程内配置（立即生效）
    settings.API_TOKEN = new_token

    # 同步当前 admin 用户的 api_token 到 users 表
    from app.core.database import get_db
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET api_token = ? WHERE user_id = ?", (new_token, current_user.user_id)
        )
        await db.commit()

    # 写入 .env 文件持久化
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    _update_env_file(env_path, "API_TOKEN", new_token)

    return {"ok": True}


def _update_env_file(env_path: Path, key: str, value: str):
    """更新 .env 文件中的指定 key"""
    lines = []
    found = False
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith(f"{key}="):
                    lines.append(f"{key}={value}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"{key}={value}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
