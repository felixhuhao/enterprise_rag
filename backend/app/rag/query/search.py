"""Milvus hybrid search node (dense + BM25) with fallback."""

from __future__ import annotations

import logging

from pymilvus import AnnSearchRequest, WeightedRanker
from langgraph.graph.state import RunnableConfig

from app.rag.embeddings.text_embedding_v4 import _text_embedding
from app.rag.query.config import QueryConfig, get_query_config
from app.rag.query.state import QueryState
from app.rag.vectorstores.general_milvus import COLLECTION_NAME, client

logger = logging.getLogger(__name__)

OUTPUT_FIELDS = [
    "content",
    "title",
    "section_title",
    "source_type",
    "table_id",
    "table_tokens",
    "raw_table_path",
    "document_id",
    "file_title",
    "entity_name",
    "part",
]


def search_node(state: QueryState, config: RunnableConfig) -> dict:
    """Hybrid search with fallback: hybrid → dense_only → error."""
    cfg = get_query_config(config)
    query = state.get("rewritten_query") or state["query"]
    entity_filter = state.get("entity_filter") or None

    try:
        query_dense = _text_embedding.embed_query(query)
    except Exception as e:
        raise RuntimeError(f"Embedding 失败: {e}") from e

    # 尝试 hybrid (dense + BM25)
    try:
        results = _hybrid_search(query_dense, query, entity_filter, cfg)
        logger.debug("Search mode: hybrid")
        return {"search_results": results}
    except Exception as e:
        logger.warning("Hybrid search failed: %s, falling back to dense_only", e)

    # fallback: dense only
    try:
        results = _dense_only_search(query_dense, entity_filter, cfg)
        logger.debug("Search mode: dense_only (fallback)")
        return {"search_results": results}
    except Exception as e:
        logger.error("Dense search also failed: %s", e)
        raise RuntimeError(f"搜索失败: {e}") from e


def _hybrid_search(query_dense, query_text, entity_filter, cfg: QueryConfig):
    dense_req = AnnSearchRequest(
        data=[query_dense],
        anns_field="dense",
        param={"metric_type": "COSINE"},
        limit=cfg.search_limit,
        expr=entity_filter,
    )
    sparse_req = AnnSearchRequest(
        data=[query_text],
        anns_field="sparse",
        param={"metric_type": "BM25"},
        limit=cfg.search_limit,
        expr=entity_filter,
    )
    results = client.hybrid_search(
        collection_name=COLLECTION_NAME,
        reqs=[dense_req, sparse_req],
        ranker=WeightedRanker(cfg.dense_weight, cfg.sparse_weight),
        limit=cfg.search_limit,
        output_fields=OUTPUT_FIELDS,
    )
    return _parse_hits(results[0])


def _dense_only_search(query_dense, entity_filter, cfg: QueryConfig):
    results = client.search(
        collection_name=COLLECTION_NAME,
        data=[query_dense],
        anns_field="dense",
        search_params={"metric_type": "COSINE"},
        limit=cfg.search_limit,
        filter=entity_filter,
        output_fields=OUTPUT_FIELDS,
    )
    return _parse_hits(results[0])


def _parse_hits(hits) -> list[dict]:
    out = []
    for hit in hits:
        entity = hit["entity"]
        out.append({
            "chunk_id": hit.get("id") or hit.get("chunk_id") or entity.get("chunk_id"),
            "document_id": entity.get("document_id", ""),
            "file_title": entity.get("file_title", ""),
            "title": entity.get("title", ""),
            "section_title": entity.get("section_title", ""),
            "source_type": entity.get("source_type", ""),
            "table_id": entity.get("table_id", ""),
            "table_tokens": entity.get("table_tokens"),
            "raw_table_path": entity.get("raw_table_path", ""),
            "content": entity.get("content", ""),
            "part": entity.get("part"),
            "score": hit["distance"],
        })
    return out
