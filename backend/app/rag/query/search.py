"""Milvus hybrid search node (dense + BM25) with fallback."""

from __future__ import annotations

import json
import logging

from pymilvus import AnnSearchRequest, WeightedRanker
from langgraph.graph.state import RunnableConfig

from app.rag.embeddings.dense_embedding import dense_embedding
from app.rag.query.config import QueryConfig, get_query_config
from app.rag.query.fallback import (
    REASON_LOW_SCORE_OR_INSUFFICIENT_HITS,
    empty_fallback_info,
    fallback_blocked,
    fallback_used,
)
from app.rag.query.filter_utils import build_acl_expr, build_entity_expr, combine_filters, get_allowed_ids
from app.rag.query.planner import plan_allows_entity_fallback, plan_budget
from app.rag.query.scoring_utils import need_fallback
from app.rag.query.state import QueryState
from app.rag.vectorstores.general_milvus import COLLECTION_NAME, client

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT = 30  # seconds


OUTPUT_FIELDS = [
    "content",
    "title",
    "section_title",
    "source_type",
    "table_id",
    "table_tokens",
    "raw_table_path",
    "document_id",
    "page",
    "file_title",
    "entity_name",
    "part",
    "table_title",
    "image_paths",
]


def search_node(state: QueryState, config: RunnableConfig) -> dict:
    """Hybrid search with fallback: hybrid → dense_only → error.
    Entity filter fallback: filtered → unfiltered if results are scarce.
    Multi-entity: per-entity parallel search + merge.
    """
    cfg = get_query_config(config)
    query = state.get("rewritten_query") or state["query"]
    entity_mode = state.get("entity_mode", "none")

    # ACL check
    allowed = get_allowed_ids(config)
    if allowed is not None and not allowed:
        return {"search_results": [], "search_mode": "acl_empty", "fallback_info": empty_fallback_info()}

    entity_filter = state.get("entity_filter") or None
    acl_filter = build_acl_expr(allowed) if allowed else None
    combined = combine_filters(entity_filter, acl_filter)

    # multi_explicit: 逐 entity 检索，合并去重
    if entity_mode == "multi_explicit":
        return _multi_entity_search(state, config, query, cfg, combined)

    # single / broad / none: 原有逻辑
    fallback_allowed = plan_allows_entity_fallback(state, config)
    budget = plan_budget(state, config)
    search_limit = int(budget.get("search_limit") or cfg.search_limit)
    return _single_search(
        query,
        entity_filter,
        cfg,
        acl_filter=acl_filter,
        fallback_allowed=fallback_allowed,
        search_limit=search_limit,
    )


def _single_search(
    query: str,
    entity_filter: str | None,
    cfg: QueryConfig,
    acl_filter: str | None = None,
    fallback_allowed: bool = True,
    search_limit: int | None = None,
) -> dict:
    """单 entity / 无 filter 的搜索。acl_filter 在 fallback 时保留。"""
    combined = combine_filters(entity_filter, acl_filter)
    limit = search_limit or cfg.search_limit

    try:
        query_dense = dense_embedding.embed_query(query)
    except Exception as e:
        raise RuntimeError(f"Embedding 失败: {e}") from e

    try:
        results = _hybrid_search(query_dense, query, combined, cfg, limit=limit)
        should_fallback = bool(entity_filter) and need_fallback(results, combined, cfg)
        info = empty_fallback_info()
        if should_fallback:
            if fallback_allowed:
                logger.info("Filtered hybrid: %d results, max_score=%.3f, retrying unfiltered",
                            len(results), max((r["score"] for r in results), default=0))
                results = _hybrid_search(query_dense, query, acl_filter, cfg, limit=limit)
                mode = "hybrid_filtered_fallback_unfiltered"
                info = fallback_used(entity_filter, REASON_LOW_SCORE_OR_INSUFFICIENT_HITS)
            else:
                mode = "hybrid_filtered"
                info = fallback_blocked(entity_filter)
        else:
            mode = "hybrid_filtered" if combined else "hybrid"
        logger.debug("Search mode: %s (%d results)", mode, len(results))
        return {"search_results": results, "search_mode": mode, "fallback_info": info}
    except Exception as e:
        logger.warning("Hybrid search failed: %s, falling back to dense_only", e)

    try:
        results = _dense_only_search(query_dense, combined, cfg, limit=limit)
        should_fallback = bool(entity_filter) and need_fallback(results, combined, cfg)
        info = empty_fallback_info()
        if should_fallback:
            if fallback_allowed:
                logger.info("Filtered dense: %d results, max_score=%.3f, retrying unfiltered",
                            len(results), max((r["score"] for r in results), default=0))
                results = _dense_only_search(query_dense, acl_filter, cfg, limit=limit)
                mode = "dense_filtered_fallback_unfiltered"
                info = fallback_used(entity_filter, REASON_LOW_SCORE_OR_INSUFFICIENT_HITS)
            else:
                mode = "dense_filtered"
                info = fallback_blocked(entity_filter)
        else:
            mode = "dense_filtered" if combined else "dense"
        logger.debug("Search mode: %s (%d results)", mode, len(results))
        return {"search_results": results, "search_mode": mode, "fallback_info": info}
    except Exception as e:
        logger.error("Dense search also failed: %s", e)
        raise RuntimeError(f"搜索失败: {e}") from e


def _multi_entity_search(state: dict, config: RunnableConfig, query: str, cfg: QueryConfig, acl_filter: str | None = None) -> dict:
    """multi_explicit: 逐 entity 检索，合并去重，记录 per_entity_counts。"""
    from concurrent.futures import ThreadPoolExecutor

    matched = state.get("matched_entities", [])
    n = max(len(matched), 1)
    budget = plan_budget(state, config)
    search_limit = int(budget.get("search_limit") or cfg.search_limit)
    per_entity_min_k = int(budget.get("per_entity_min_k") or 5)
    per_limit = max(search_limit // n, per_entity_min_k)

    # embedding 只算一次
    try:
        query_dense = dense_embedding.embed_query(query)
    except Exception as e:
        raise RuntimeError(f"Embedding 失败: {e}") from e

    def _search_one(entity: str) -> tuple[str, list[dict], str]:
        ef = combine_filters(build_entity_expr(entity), acl_filter) or build_entity_expr(entity)
        try:
            results = _hybrid_search_limited(query_dense, query, ef, per_limit, cfg)
            return entity, results, "hybrid_filtered"
        except Exception:
            pass
        try:
            results = _dense_only_search_limited(query_dense, ef, per_limit)
            return entity, results, "dense_filtered"
        except Exception:
            return entity, [], "failed"

    # 并行检索每个 entity
    all_results: list[dict] = []
    per_counts: dict[str, int] = {}
    modes: set[str] = set()
    all_failed = True

    with ThreadPoolExecutor(max_workers=min(n, 4)) as pool:
        futures = [pool.submit(_search_one, e) for e in matched]
        for f in futures:
            entity, results, mode = f.result()
            per_counts[entity] = len(results)
            all_results.extend(results)
            if mode != "failed":
                modes.add(mode)
                all_failed = False

    # 全部 entity 失败 → 必须抛出
    if all_failed:
        raise RuntimeError(f"多实体检索全部失败: entities={matched}")

    # 按 chunk_id 去重，保留最高分；不过早截断，留给 RRF/rerank
    seen: dict[str, dict] = {}
    for r in all_results:
        key = str(r.get("chunk_id") or f"{r.get('document_id')}|{r.get('source_type')}|{r.get('part')}")
        if key not in seen or r["score"] > seen[key]["score"]:
            seen[key] = r

    # 保留上限放宽到 2x，保证每个 entity 都有机会进入 rerank
    cap = min(len(seen), search_limit * 2)
    merged = sorted(seen.values(), key=lambda x: x["score"], reverse=True)[:cap]
    mode = "multi_" + "+".join(sorted(modes))

    logger.info("Multi-entity search: entities=%s, total=%d, merged=%d",
                matched, len(all_results), len(merged))

    return {
        "search_results": merged,
        "search_mode": mode,
        "per_entity_counts": per_counts,
        "fallback_info": empty_fallback_info(),
    }


def _hybrid_search_limited(query_dense, query_text, entity_filter, limit: int, cfg: QueryConfig):
    """Hybrid search with custom limit for per-entity retrieval."""
    dense_req = AnnSearchRequest(
        data=[query_dense],
        anns_field="dense",
        param={"metric_type": "COSINE"},
        limit=limit,
        expr=entity_filter,
    )
    sparse_req = AnnSearchRequest(
        data=[query_text],
        anns_field="sparse",
        param={"metric_type": "BM25"},
        limit=limit,
        expr=entity_filter,
    )
    results = client.hybrid_search(
        collection_name=COLLECTION_NAME,
        reqs=[dense_req, sparse_req],
        ranker=WeightedRanker(cfg.dense_weight, cfg.sparse_weight),
        limit=limit,
        output_fields=OUTPUT_FIELDS,
        timeout=SEARCH_TIMEOUT,
    )
    return _parse_hits(results[0])


def _dense_only_search_limited(query_dense, entity_filter, limit: int):
    """Dense search with custom limit for per-entity retrieval."""
    results = client.search(
        collection_name=COLLECTION_NAME,
        data=[query_dense],
        anns_field="dense",
        search_params={"metric_type": "COSINE"},
        limit=limit,
        filter=entity_filter,
        output_fields=OUTPUT_FIELDS,
        timeout=SEARCH_TIMEOUT,
    )
    return _parse_hits(results[0])


def _hybrid_search(query_dense, query_text, entity_filter, cfg: QueryConfig, limit: int | None = None):
    limit = limit or cfg.search_limit
    dense_req = AnnSearchRequest(
        data=[query_dense],
        anns_field="dense",
        param={"metric_type": "COSINE"},
        limit=limit,
        expr=entity_filter,
    )
    sparse_req = AnnSearchRequest(
        data=[query_text],
        anns_field="sparse",
        param={"metric_type": "BM25"},
        limit=limit,
        expr=entity_filter,
    )
    results = client.hybrid_search(
        collection_name=COLLECTION_NAME,
        reqs=[dense_req, sparse_req],
        ranker=WeightedRanker(cfg.dense_weight, cfg.sparse_weight),
        limit=limit,
        output_fields=OUTPUT_FIELDS,
        timeout=SEARCH_TIMEOUT,
    )
    return _parse_hits(results[0])


def _dense_only_search(query_dense, entity_filter, cfg: QueryConfig, limit: int | None = None):
    limit = limit or cfg.search_limit
    results = client.search(
        collection_name=COLLECTION_NAME,
        data=[query_dense],
        anns_field="dense",
        search_params={"metric_type": "COSINE"},
        limit=limit,
        filter=entity_filter,
        output_fields=OUTPUT_FIELDS,
        timeout=SEARCH_TIMEOUT,
    )
    return _parse_hits(results[0])


def _parse_hits(hits) -> list[dict]:
    out = []
    for hit in hits:
        entity = hit["entity"]
        out.append({
            "chunk_id": hit.get("id") or hit.get("chunk_id") or entity.get("chunk_id"),
            "document_id": entity.get("document_id", ""),
            "page": entity.get("page"),
            "file_title": entity.get("file_title", ""),
            "entity_name": entity.get("entity_name", ""),
            "title": entity.get("title", ""),
            "section_title": entity.get("section_title", ""),
            "source_type": entity.get("source_type", ""),
            "table_id": entity.get("table_id", ""),
            "table_title": entity.get("table_title", ""),
            "table_tokens": entity.get("table_tokens"),
            "raw_table_path": entity.get("raw_table_path", ""),
            "content": entity.get("content", ""),
            "part": entity.get("part"),
            "image_paths": json.loads(entity.get("image_paths") or "[]"),
            "score": hit["distance"],
        })
    return out
