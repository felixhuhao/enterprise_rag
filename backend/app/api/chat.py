"""
聊天 API 端点模块

提供聊天消息接口，接收用户发送的文本或图片消息，
通过 SSE（Server-Sent Events）流式返回 AI 的回复。

端点：
- POST /chat: 发送聊天消息，返回 SSE 流式响应
"""

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.deps import verify_token
from app.models.schemas import ChatRequest
from app.services.chat_service import chat_stream_generator

router = APIRouter()


@router.post("/chat")
async def chat(
    request: ChatRequest,
    _: None = Depends(verify_token),
):
    """
    发送聊天消息，返回 SSE 流式响应

    接收包含文本和/或图片的消息，调用核心聊天服务生成 SSE 事件流。
    前端通过 EventSource 接口逐步接收 AI 回复、工具调用结果和状态事件。

    参数:
        request: 聊天请求体，包含 session_id、text 和 image_base64
        _: Token 验证依赖（未使用返回值，仅做鉴权校验）

    返回:
        EventSourceResponse: SSE 流式响应，事件类型包括
            message_start、assistant_chunk、tool_call、interrupt、message_end、error
    """
    generator = chat_stream_generator(
        session_id=request.session_id,
        text=request.text,
        image_base64=request.image_base64,
    )
    return EventSourceResponse(generator)
