"""
会话管理模块（SQLite 持久化）

提供会话注册表，管理用户聊天会话的创建、查询、删除等操作。
所有会话数据持久化到 SQLite 数据库，进程重启后不丢失。
"""

import uuid
from datetime import datetime

from app.core.database import get_db


class SessionManager:
    """
    会话注册表（SQLite 持久化）

    所有会话元数据存储在 SQLite sessions 表中。
    """

    async def create(self, user_name: str = "ZS") -> dict:
        """
        创建新会话

        参数:
            user_name: 用户名，默认 "ZS"

        返回:
            新创建的会话信息字典
        """
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        async with get_db() as db:
            await db.execute(
                "INSERT INTO sessions (session_id, user_name, created_at, status) VALUES (?, ?, ?, ?)",
                (session_id, user_name, now, "active"),
            )
            await db.commit()
        return {
            "session_id": session_id,
            "user_name": user_name,
            "created_at": now,
            "status": "active",
        }

    async def get(self, session_id: str) -> dict | None:
        """
        根据 session_id 查询会话

        参数:
            session_id: 会话唯一标识

        返回:
            会话信息字典，不存在则返回 None
        """
        async with get_db() as db:
            async with db.execute(
                "SELECT session_id, user_name, created_at, status FROM sessions WHERE session_id = ?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None

    async def list_all(self) -> list[dict]:
        """
        列出所有会话

        返回:
            所有会话信息字典组成的列表
        """
        async with get_db() as db:
            async with db.execute(
                "SELECT session_id, user_name, created_at, status FROM sessions ORDER BY created_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def update_status(self, session_id: str, status: str):
        """
        更新会话状态

        参数:
            session_id: 会话唯一标识
            status: 新的状态值（如 "active"、"closed"）
        """
        async with get_db() as db:
            await db.execute(
                "UPDATE sessions SET status = ? WHERE session_id = ?",
                (status, session_id),
            )
            await db.commit()

    async def delete(self, session_id: str) -> bool:
        """
        删除指定会话

        参数:
            session_id: 会话唯一标识

        返回:
            True 表示删除成功，False 表示会话不存在
        """
        async with get_db() as db:
            cursor = await db.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
            await db.commit()
            return cursor.rowcount > 0


# 全局单例，整个应用共享同一个 SessionManager 实例
session_manager = SessionManager()
