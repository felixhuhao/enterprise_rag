"""
审批 API 端点模块

提供人工审批（human-in-the-loop）相关接口。
当 AI 回复需要人工确认时，用户可通过批准或拒绝操作控制工作流走向：
- 批准：接受当前 AI 回复，继续后续流程
- 拒绝：拒绝当前回复，触发网络搜索重新生成答案

端点：
- POST /chat/approve: 批准 AI 回复
- POST /chat/reject: 拒绝 AI 回复
"""

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.deps import verify_token
from app.models.schemas import ApprovalRequest
from app.services.approval_service import approval_stream_generator

router = APIRouter()


@router.post("/chat/approve")
async def approve(
    request: ApprovalRequest,
    _: None = Depends(verify_token),
):
    """
    批准 AI 回复

    将审批结果设为 "approve"，从图中断点恢复执行。
    批准后图将继续按正常流程执行后续节点。

    参数:
        request: 审批请求体，包含 session_id
        _: Token 验证依赖

    返回:
        EventSourceResponse: SSE 流式响应，包含恢复执行后的 AI 回复
    """
    generator = approval_stream_generator(request.session_id, "approve")
    return EventSourceResponse(generator)


@router.post("/chat/reject")
async def reject(
    request: ApprovalRequest,
    _: None = Depends(verify_token),
):
    """
    拒绝 AI 回复，触发网络搜索重新生成

    将审批结果设为 "rejected"，图中断恢复后会走网络搜索分支，
    从互联网检索信息并重新生成答案。

    参数:
        request: 审批请求体，包含 session_id
        _: Token 验证依赖

    返回:
        EventSourceResponse: SSE 流式响应，包含网络搜索后重新生成的 AI 回复
    """
    generator = approval_stream_generator(request.session_id, "rejected")
    return EventSourceResponse(generator)
