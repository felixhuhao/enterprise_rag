"""
评估数据服务模块

提供评估统计、分布、趋势的查询逻辑。
评估数据在聊天流结束时由 chat_service.py 写入 evaluate_records 表。
"""

from datetime import datetime

from app.config import settings
from app.core.database import get_db


class EvaluateService:
    """评估数据查询服务"""

    async def save_record(
        self, session_id: str, input_text: str, score: float, from_web_search: bool
    ):
        """保存一条评估记录"""
        now = datetime.now().isoformat()
        async with get_db() as db:
            await db.execute(
                """INSERT INTO evaluate_records (session_id, input_text, score, from_web_search, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, input_text[:200], score, int(from_web_search), now),
            )
            await db.commit()

    async def get_stats(self) -> dict:
        """获取聚合统计数据"""
        high_threshold = settings.EVALUATE_THRESHOLD_HIGH
        low_threshold = settings.EVALUATE_THRESHOLD_LOW
        async with get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) as total, AVG(score) as avg_score FROM evaluate_records"
            ) as cursor:
                row = await cursor.fetchone()
                total = row["total"]
                avg_score = row["avg_score"] or 0.0

            async with db.execute(
                "SELECT COUNT(*) as cnt FROM evaluate_records WHERE score >= ?",
                (high_threshold,),
            ) as cursor:
                high = (await cursor.fetchone())["cnt"]

            async with db.execute(
                "SELECT COUNT(*) as cnt FROM evaluate_records WHERE score >= ? AND score < ?",
                (low_threshold, high_threshold),
            ) as cursor:
                mid = (await cursor.fetchone())["cnt"]

            async with db.execute(
                "SELECT COUNT(*) as cnt FROM evaluate_records WHERE score < ?",
                (low_threshold,),
            ) as cursor:
                low = (await cursor.fetchone())["cnt"]

            async with db.execute(
                "SELECT COUNT(*) as cnt FROM evaluate_records WHERE from_web_search = 1"
            ) as cursor:
                web_count = (await cursor.fetchone())["cnt"]

        return {
            "total_count": total,
            "avg_score": round(avg_score, 3),
            "high_count": high,
            "mid_count": mid,
            "low_count": low,
            "web_search_count": web_count,
        }

    async def get_distribution(self) -> dict:
        """获取分数分布（0.2 为一档）"""
        bins = [
            ("0.0-0.2", 0.0, 0.2),
            ("0.2-0.4", 0.2, 0.4),
            ("0.4-0.6", 0.4, 0.6),
            ("0.6-0.8", 0.6, 0.8),
            ("0.8-1.0", 0.8, 1.01),
        ]
        result = []
        async with get_db() as db:
            for label, lo, hi in bins:
                async with db.execute(
                    "SELECT COUNT(*) as cnt FROM evaluate_records WHERE score >= ? AND score < ?",
                    (lo, hi),
                ) as cursor:
                    cnt = (await cursor.fetchone())["cnt"]
                result.append({"range": label, "count": cnt})
        return {"bins": result}

    async def get_trend(self) -> dict:
        """获取每日平均分趋势"""
        async with get_db() as db:
            async with db.execute(
                """SELECT DATE(created_at) as date,
                          AVG(score) as avg_score,
                          COUNT(*) as count
                   FROM evaluate_records
                   GROUP BY DATE(created_at)
                   ORDER BY date DESC
                   LIMIT 30"""
            ) as cursor:
                rows = await cursor.fetchall()
        return {
            "dates": [row["date"] for row in rows],
            "avg_scores": [round(row["avg_score"], 3) for row in rows],
            "counts": [row["count"] for row in rows],
        }

    async def get_records(self, page: int = 1, page_size: int = 20) -> dict:
        """获取分页评估记录"""
        offset = (page - 1) * page_size
        async with get_db() as db:
            async with db.execute(
                """SELECT id, session_id, input_text, score, from_web_search, created_at
                   FROM evaluate_records
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (page_size, offset),
            ) as cursor:
                rows = await cursor.fetchall()
                records = [dict(row) for row in rows]

            async with db.execute("SELECT COUNT(*) as total FROM evaluate_records") as cursor:
                total = (await cursor.fetchone())["total"]

        return {
            "records": records,
            "total": total,
            "page": page,
            "page_size": page_size,
        }


evaluate_service = EvaluateService()
