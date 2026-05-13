"""
会话管理 API 端点模块

提供聊天会话的增删查操作，所有接口均需 Token 鉴权。

端点：
- POST /sessions: 创建新的聊天会话
- GET /sessions: 列出所有会话
- DELETE /sessions/{session_id}: 删除指定会话
"""

from fastapi import APIRouter, Depends, HTTPException

from app.deps import verify_token
from app.core.session_manager import session_manager
from app.core.graph_manager import graph_manager
from app.models.schemas import SessionCreateRequest, SessionInfo

router = APIRouter()


@router.post("/sessions", response_model=SessionInfo)
async def create_session(
    request: SessionCreateRequest = SessionCreateRequest(),
    _: None = Depends(verify_token),
):
    """
    创建新的聊天会话

    参数:
        request: 创建会话请求体，可指定 user_name，默认 "ZS"
        _: Token 验证依赖

    返回:
        SessionInfo: 新创建的会话信息
    """
    return await session_manager.create(user_name=request.user_name)


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(_: None = Depends(verify_token)):
    """
    列出所有会话

    参数:
        _: Token 验证依赖

    返回:
        list[SessionInfo]: 所有会话信息列表
    """
    return await session_manager.list_all()


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, _: None = Depends(verify_token)):
    """
    删除指定会话

    参数:
        session_id: 要删除的会话唯一标识
        _: Token 验证依赖

    返回:
        dict: {"ok": True} 表示删除成功
    """
    if not await session_manager.delete(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    graph_manager.remove_lock(session_id)
    return {"ok": True}
