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
    ):
        """保存一次查询统计。"""
        now = datetime.now().isoformat()
        async with get_db() as db:
            await db.execute(
                """INSERT INTO query_run_stats
                   (session_id, query, search_mode, search_mode_hyde,
                    result_count, rerank_avg_score, rerank_top_score,
                    retrieval_wall_ms, first_token_ms, generate_ms, total_ms,
                    status, error_code, retrieved_chunks, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, query[:500], search_mode, search_mode_hyde,
                 result_count, rerank_avg_score, rerank_top_score,
                 retrieval_wall_ms, first_token_ms, generate_ms, total_ms,
                 status, error_code, retrieved_chunks, now),
            )
            await db.commit()

    async def get_stats(self) -> dict:
        """聚合统计。平均值只算 success，fallback 只算 success。"""
        async with get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) as total_queries, "
                "COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) as success_count, "
                "COALESCE(AVG(CASE WHEN status = 'success' THEN rerank_avg_score END), 0) as avg_rerank, "
                "COALESCE(AVG(CASE WHEN status = 'success' THEN result_count END), 0) as avg_result_count, "
                "COALESCE(SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END), 0) as total_failed, "
                "COALESCE(SUM(CASE WHEN status = 'success' "
                "  AND (search_mode LIKE '%fallback%' OR search_mode_hyde LIKE '%fallback%') "
                "  THEN 1 ELSE 0 END), 0) as fallback_count "
                "FROM query_run_stats"
            ) as cursor:
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
        }

    async def get_trend(self, days: int = 30) -> dict:
        """每日趋势。"""
        async with get_db() as db:
            async with db.execute(
                """SELECT DATE(created_at) as date,
                          AVG(CASE WHEN status = 'success' THEN rerank_avg_score END) as avg_rerank,
                          AVG(CASE WHEN status = 'success' THEN result_count END) as avg_result_count,
                          COUNT(*) as count,
                          SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failed_count
                   FROM query_run_stats
                   GROUP BY DATE(created_at)
                   ORDER BY date DESC
                   LIMIT ?""",
                (days,),
            ) as cursor:
                rows = await cursor.fetchall()
        return {
            "dates": [row["date"] for row in rows],
            "avg_rerank": [round(row["avg_rerank"] or 0, 3) for row in rows],
            "avg_result_count": [round(row["avg_result_count"] or 0, 1) for row in rows],
            "counts": [row["count"] for row in rows],
            "failed_counts": [row["failed_count"] for row in rows],
        }

    async def get_records(self, page: int = 1, page_size: int = 20) -> dict:
        """分页查询记录。"""
        offset = (page - 1) * page_size
        async with get_db() as db:
            async with db.execute(
                """SELECT id, session_id, query, search_mode, search_mode_hyde,
                          result_count, rerank_avg_score, rerank_top_score,
                          retrieval_wall_ms, first_token_ms, generate_ms, total_ms,
                          status, error_code, retrieved_chunks, created_at
                   FROM query_run_stats
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (page_size, offset),
            ) as cursor:
                rows = await cursor.fetchall()
                records = [dict(row) for row in rows]

            async with db.execute("SELECT COUNT(*) as total FROM query_run_stats") as cursor:
                total = (await cursor.fetchone())["total"]

        return {
            "records": records,
            "total": total,
            "page": page,
            "page_size": page_size,
        }


query_stats_service = QueryStatsService()
