"""Query run statistics — persistent storage for rerank/search stats."""

from datetime import datetime

from app.core.database import get_db


class QueryStatsService:
    """检索统计读写服务"""

    async def save(
        self,
        session_id: str,
        query: str,
        search_mode: str,
        search_mode_hyde: str,
        result_count: int,
        rerank_avg_score: float,
        rerank_top_score: float,
        retrieval_wall_ms: int = 0,
        first_token_ms: int = 0,
        generate_ms: int = 0,
        total_ms: int = 0,
        status: str = "success",
        error_code: str = "",
        retrieved_chunks: str = "[]",
        groundedness_score: float | None = None,
        user_id: str = "",
    ):
        """保存一次查询统计。"""
        now = datetime.now().isoformat()
        async with get_db() as db:
            await db.execute(
                """INSERT INTO query_run_stats
                   (session_id, query, search_mode, search_mode_hyde,
                    result_count, rerank_avg_score, rerank_top_score,
                    retrieval_wall_ms, first_token_ms, generate_ms, total_ms,
                    status, error_code, retrieved_chunks, groundedness_score, user_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, query[:500], search_mode, search_mode_hyde,
                 result_count, rerank_avg_score, rerank_top_score,
                 retrieval_wall_ms, first_token_ms, generate_ms, total_ms,
                 status, error_code, retrieved_chunks, groundedness_score, user_id, now),
            )
            await db.commit()

    async def get_stats(self, user_id: str | None = None) -> dict:
        """聚合统计。user_id 非空时只统计该用户；None = admin 看全部。"""
        where = "WHERE user_id = ?" if user_id else ""
        params = (user_id,) if user_id else ()
        async with get_db() as db:
            sql = (
                "SELECT COUNT(*) as total_queries, "
                "COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) as success_count, "
                "COALESCE(AVG(CASE WHEN status = 'success' THEN rerank_avg_score END), 0) as avg_rerank, "
                "COALESCE(AVG(CASE WHEN status = 'success' THEN result_count END), 0) as avg_result_count, "
                "COALESCE(SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END), 0) as total_failed, "
                "COALESCE(SUM(CASE WHEN status = 'success' "
                "  AND (search_mode LIKE '%fallback%' OR search_mode_hyde LIKE '%fallback%') "
                "  THEN 1 ELSE 0 END), 0) as fallback_count, "
                "AVG(CASE WHEN status = 'success' AND groundedness_score IS NOT NULL "
                "  THEN groundedness_score END) as avg_groundedness_score, "
                "COALESCE(SUM(CASE WHEN status = 'success' AND groundedness_score IS NOT NULL "
                "  AND groundedness_score < 0.7 THEN 1 ELSE 0 END), 0) as low_groundedness_count "
                f"FROM query_run_stats {where}"
            )
            async with db.execute(sql, params) as cursor:
                row = dict(await cursor.fetchone())

        total = row["total_queries"] or 0
        success_count = row["success_count"] or 0
        total_failed = row["total_failed"] or 0
        fallback_count = row["fallback_count"] or 0
        return {
            "total_queries": total,
            "success_count": success_count,
            "total_failed": total_failed,
            "failure_rate": round(total_failed / total, 3) if total else 0,
            "avg_rerank_score": round(row["avg_rerank"], 3),
            "avg_result_count": round(row["avg_result_count"], 1),
            "fallback_count": fallback_count,
            "fallback_ratio": round(fallback_count / success_count, 3) if success_count else 0,
            "avg_groundedness_score": round(row["avg_groundedness_score"], 3) if row["avg_groundedness_score"] is not None else None,
            "low_groundedness_count": row["low_groundedness_count"] or 0,
        }

    async def get_trend(self, days: int = 30, user_id: str | None = None) -> dict:
        """每日趋势。user_id 非空时过滤。"""
        where = "WHERE user_id = ?" if user_id else ""
        extra = (user_id,) if user_id else ()
        async with get_db() as db:
            async with db.execute(
                f"""SELECT DATE(created_at) as date,
                          AVG(CASE WHEN status = 'success' THEN rerank_avg_score END) as avg_rerank,
                          AVG(CASE WHEN status = 'success' THEN result_count END) as avg_result_count,
                          COUNT(*) as count,
                          SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failed_count
                   FROM query_run_stats {where}
                   GROUP BY DATE(created_at)
                   ORDER BY date DESC
                   LIMIT ?""",
                (*extra, days),
            ) as cursor:
                rows = await cursor.fetchall()
        return {
            "dates": [row["date"] for row in rows],
            "avg_rerank": [round(row["avg_rerank"] or 0, 3) for row in rows],
            "avg_result_count": [round(row["avg_result_count"] or 0, 1) for row in rows],
            "counts": [row["count"] for row in rows],
            "failed_counts": [row["failed_count"] for row in rows],
        }

    async def get_records(self, page: int = 1, page_size: int = 20, user_id: str | None = None) -> dict:
        """分页查询记录。user_id 非空时过滤。"""
        offset = (page - 1) * page_size
        where = "WHERE user_id = ?" if user_id else ""
        user_param = (user_id,) if user_id else ()
        async with get_db() as db:
            async with db.execute(
                f"""SELECT id, session_id, query, search_mode, search_mode_hyde,
                          result_count, rerank_avg_score, rerank_top_score,
                          retrieval_wall_ms, first_token_ms, generate_ms, total_ms,
                          status, error_code, retrieved_chunks, groundedness_score, user_id, created_at
                   FROM query_run_stats {where}
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (*user_param, page_size, offset),
            ) as cursor:
                rows = await cursor.fetchall()
                records = [dict(row) for row in rows]

            count_sql = f"SELECT COUNT(*) as total FROM query_run_stats {where}"
            async with db.execute(count_sql, user_param) as cursor:
                total = (await cursor.fetchone())["total"]

        return {
            "records": records,
            "total": total,
            "page": page,
            "page_size": page_size,
        }


query_stats_service = QueryStatsService()
