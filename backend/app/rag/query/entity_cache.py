"""Known entity_name cache from Milvus."""

from __future__ import annotations

import logging
import threading

from app.rag.vectorstores.general_milvus import COLLECTION_NAME, client

logger = logging.getLogger(__name__)

_cache: set[str] = set()
_lock = threading.Lock()


def get_known_entities() -> set[str]:
    """获取已知 entity_name 集合（懒加载 + 缓存）。"""
    with _lock:
        if not _cache:
            _do_refresh()
        return _cache


def _do_refresh():
    """内部刷新，调用方已持有 _lock。"""
    global _cache
    results = client.query(
        collection_name=COLLECTION_NAME,
        filter='entity_name != \"\"',
        output_fields=["entity_name"],
        limit=10000,
    )
    names = {r["entity_name"] for r in results if r.get("entity_name")}
    _cache = names
    logger.info("Entity cache refreshed: %d entities", len(names))


def invalidate():
    """清空缓存，下次查询时重新加载。"""
    global _cache
    with _lock:
        _cache = set()
