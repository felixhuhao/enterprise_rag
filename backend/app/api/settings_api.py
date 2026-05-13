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

from app.deps import verify_token
from app.config import settings
from app.core.runtime_settings import runtime_settings
from app.models.schemas import SettingsUpdate, TokenUpdate

router = APIRouter()


@router.get("/settings")
async def get_settings(_: None = Depends(verify_token)):
    """
    获取所有运行时设置

    返回:
        dict: { key: value, ... }
    """
    return await runtime_settings.get_all()


@router.put("/settings")
async def update_settings(
    request: SettingsUpdate,
    _: None = Depends(verify_token),
):
    """
    批量更新运行时设置

    参数:
        request: 设置更新请求体 { settings: { key: value, ... } }

    返回:
        dict: 更新后的完整设置
    """
    if not request.settings:
        raise HTTPException(status_code=400, detail="settings 不能为空")
    await runtime_settings.update_batch(request.settings)
    return await runtime_settings.get_all()


@router.post("/settings/token")
async def update_token(
    request: TokenUpdate,
    _: None = Depends(verify_token),
):
    """
    更新 API Token

    更新当前进程的 API Token，立即生效。同时写入 .env 文件持久化。

    参数:
        request: Token 更新请求体 { token: "新 token" }
    """
    new_token = request.token.strip()
    if not new_token:
        raise HTTPException(status_code=400, detail="Token 不能为空")

    # 更新进程内配置（立即生效）
    settings.API_TOKEN = new_token

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
