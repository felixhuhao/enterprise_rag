"""
Pydantic 数据模型定义模块

定义所有 API 请求和响应的数据结构（Schema），用于：
- 自动生成请求参数校验
- 自动生成 OpenAPI 文档
- 统一前后端数据交互格式
"""

from pydantic import BaseModel, Field


# ---- 设置相关 ----

class SettingsUpdate(BaseModel):
    """设置批量更新请求"""
    settings: dict[str, str]


class TokenUpdate(BaseModel):
    """API Token 更新请求"""
    token: str = Field(..., min_length=1, max_length=512)
