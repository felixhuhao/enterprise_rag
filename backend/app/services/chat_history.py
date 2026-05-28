"""Query chat history persistence."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.core.database import get_db

logger = logging.getLogger(__name__)


async def save_message(
    session_id: str,
    role: str,
    content: str,
    citations: list[dict] | None = None,
    user_id: str = "",
) -> None:
    """保存一条聊天记录。"""
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO query_chat_messages (session_id, role, content, citations, user_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, role, content, json.dumps(citations or [], ensure_ascii=False), user_id, now),
        )
        await db.commit()


async def load_history(session_id: str, user_id: str = "", limit: int = 20) -> list[dict]:
    """加载最近 N 条聊天记录。按 session + user 隔离。"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT role, content, citations, created_at FROM query_chat_messages "
            "WHERE session_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, user_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "role": row["role"],
                "content": row["content"],
                "citations": json.loads(row["citations"]),
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]
