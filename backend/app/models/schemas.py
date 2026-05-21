"""
Pydantic 数据模型定义模块

定义所有 API 请求和响应的数据结构（Schema），用于：
- 自动生成请求参数校验
- 自动生成 OpenAPI 文档
- 统一前后端数据交互格式

包含的模型：
- ChatRequest: 聊天请求（支持纯文本和多模态图片输入）
- ApprovalRequest: 审批请求
- SessionCreateRequest: 创建会话请求
- SessionInfo: 会话信息响应
"""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """
    聊天请求模型

    支持纯文本消息和多模态（文本+图片）消息。
    text 和 image_base64 至少需要提供一个。
    """
    session_id: str  # 会话唯一标识
    text: str | None = None  # 文本消息内容
    image_base64: str | None = None  # 图片的 Base64 编码（格式：data:image/png;base64,...）


class ApprovalRequest(BaseModel):
    """
    审批请求模型

    用于对 AI 回复进行人工审批（批准或拒绝），仅需提供会话 ID。
    """
    session_id: str  # 需要审批的会话唯一标识


class SessionCreateRequest(BaseModel):
    """
    创建会话请求模型

    创建新的聊天会话时可指定用户名，默认为 "ZS"。
    """
    user_name: str = "ZS"  # 用户名，默认值 "ZS"


class SessionInfo(BaseModel):
    """
    会话信息响应模型

    返回给前端的会话元数据，包含 ID、用户名、创建时间和状态。
    """
    session_id: str  # 会话唯一标识
    user_name: str  # 用户名
    created_at: str  # 创建时间（ISO 格式字符串）
    status: str  # 会话状态（如 "active"、"closed"）


# ---- 设置相关 ----

class SettingsUpdate(BaseModel):
    """设置批量更新请求"""
    settings: dict[str, str]


class TokenUpdate(BaseModel):
    """API Token 更新请求"""
    token: str


# ---- 知识库相关 ----

class KnowledgeDocumentInfo(BaseModel):
    """知识库文档信息响应"""
    id: int
    filename: str
    source: str
    status: str  # uploaded | parsing | parsed | saving | completed | failed
    doc_count: int = 0
    image_count: int = 0
    error_msg: str = ""
    created_at: str
    updated_at: str


class GeneralDocumentInfo(BaseModel):
    """通用导入文档信息响应"""
    id: int
    document_id: str
    filename: str
    source_path: str
    file_type: str
    ingestion_mode: str = "text_only"
    status: str
    chunk_count: int = 0
    image_count: int = 0
    error_msg: str = ""
    created_at: str
    updated_at: str


# ---- 评估相关 ----

class EvaluateStats(BaseModel):
    """评估统计数据"""
    total_count: int = 0
    avg_score: float = 0.0
    high_count: int = 0    # >= 0.8
    mid_count: int = 0     # 0.6 ~ 0.8
    low_count: int = 0     # < 0.6
    web_search_count: int = 0
