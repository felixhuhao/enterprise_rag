"""Known entity and alias cache for query-time entity routing."""

from __future__ import annotations

import logging
import sqlite3
import threading

from app.config import settings
from app.rag.vectorstores.general_milvus import COLLECTION_NAME, client

logger = logging.getLogger(__name__)

_cache: set[str] = set()
_alias_cache: dict[str, list[str]] = {}
_loaded = False
_lock = threading.Lock()


def get_known_entities() -> set[str]:
    """Return known canonical entity names from Milvus."""
    with _lock:
        if not _loaded:
            _do_refresh()
        return _cache


def get_alias_map() -> dict[str, list[str]]:
    """Return alias -> canonical entity names mapping from SQLite."""
    with _lock:
        if not _loaded:
            _do_refresh()
        return _alias_cache


def _do_refresh():
    """Refresh both canonical entities and aliases. Caller must hold _lock."""
    global _cache, _alias_cache, _loaded
    results = client.query(
        collection_name=COLLECTION_NAME,
        filter='entity_name != ""',
        output_fields=["entity_name"],
        limit=10000,
    )
    _cache = {r["entity_name"] for r in results if r.get("entity_name")}
    _alias_cache = _load_aliases()
    _loaded = True
    logger.info("Entity cache refreshed: %d entities, %d aliases", len(_cache), len(_alias_cache))


def _load_aliases() -> dict[str, list[str]]:
    aliases: dict[str, list[str]] = {}
    try:
        with sqlite3.connect(settings.DATABASE_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT alias, canonical_entity FROM entity_aliases ORDER BY alias, canonical_entity"
            ).fetchall()
    except sqlite3.Error:
        logger.warning("Failed to load entity aliases", exc_info=True)
        return aliases

    for row in rows:
        alias = row["alias"]
        canonical = row["canonical_entity"]
        if not alias or not canonical:
            continue
        bucket = aliases.setdefault(alias, [])
        if canonical not in bucket:
            bucket.append(canonical)
    return aliases


def invalidate():
    """Clear cache so the next query reloads entities and aliases."""
    global _cache, _alias_cache, _loaded
    with _lock:
        _cache = set()
        _alias_cache = {}
        _loaded = False
