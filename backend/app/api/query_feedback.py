"""Answer feedback — POST /query/feedback, GET /query/feedback (admin)."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.deps import verify_token

router = APIRouter()


class FeedbackRequest(BaseModel):
    session_id: str
    message_id: str = ""
    query: str = Field(..., max_length=4000)
    answer: str = ""
    citations: list[dict] = []
    retrieved_chunks: list[dict] = []
    rating: str  # "up" | "down"
    comment: str = ""


@router.post("/query/feedback")
async def submit_feedback(
    body: FeedbackRequest,
    current_user: CurrentUser = Depends(verify_token),
):
    """提交答案反馈。"""
    if body.rating not in ("up", "down"):
        raise HTTPException(status_code=400, detail="rating must be 'up' or 'down'")

    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO query_feedback "
            "(session_id, message_id, query, answer, citations, retrieved_chunks, "
            "rating, comment, user_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                body.session_id, body.message_id, body.query, body.answer,
                json.dumps(body.citations, ensure_ascii=False),
                json.dumps(body.retrieved_chunks, ensure_ascii=False),
                body.rating, body.comment[:500],
                current_user.user_id, now,
            ),
        )
        await db.commit()
    return {"ok": True}


@router.get("/query/feedback")
async def list_feedback(current_user: CurrentUser = Depends(verify_token)):
    """返回所有反馈记录（admin only）。"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看反馈")

    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM query_feedback ORDER BY created_at DESC LIMIT 200"
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]
