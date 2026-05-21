"""Pure scoring helpers — no Milvus / external service imports."""

from __future__ import annotations

from app.rag.query.config import QueryConfig


def need_fallback(results: list[dict], entity_filter: str | None, cfg: QueryConfig) -> bool:
    """是否需要 fallback 到无 filter 搜索。"""
    if not entity_filter:
        return False
    if len(results) < cfg.entity_filter_min_results:
        return True
    max_score = max((r["score"] for r in results), default=0)
    if max_score < cfg.entity_filter_min_score:
        return True
    return False


def cliff_detect(results: list[dict], cfg: QueryConfig) -> int:
    """分数断崖检测。"""
    n = min(len(results), cfg.rerank_max_top_k)
    if n <= cfg.rerank_min_top_k:
        return n

    for i in range(cfg.rerank_min_top_k, n):
        drop = results[i - 1]["score"] - results[i]["score"]
        if drop > cfg.rerank_cliff_threshold:
            return i

    return n
