"""Vector-space fingerprint guard.

Prevents silently mixing incompatible embedding vector spaces when the
embedding provider/model/dim changes but the Milvus collection is not reset.

The fingerprint is persisted in the existing SQLite ``settings`` KV table
(created by ``init_db``) using a dedicated sync helper so it can be read from
sync LangGraph nodes (query / upsert) without crossing async boundaries.

Guard policy (strict default):
    - Collection does not exist  → no-op (nothing to protect).
    - Collection exists, no stored fingerprint → block (operator must pin or reset).
    - Stored fingerprint != current → block (reset + reindex required).
    - Stored == current → ok.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from app.config import settings

logger = logging.getLogger(__name__)

#: Matches ``general_milvus.COLLECTION_NAME``. Hardcoded here to avoid a circular
#: import (general_milvus imports this module to record/verify the fingerprint).
_COLLECTION_NAME = "general_documents"
FINGERPRINT_KEY = f"milvus.{_COLLECTION_NAME}.embedding_fingerprint"


def current_fingerprint() -> str:
    """Return the fingerprint of the currently configured embedding backend."""
    return json.dumps(
        {
            "provider": settings.EMBEDDING_PROVIDER.strip().lower(),
            "model": settings.EMBEDDING_MODEL_NAME.strip(),
            "dim": settings.EMBEDDING_DIM,
        },
        sort_keys=True,
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def stored_fingerprint() -> str | None:
    """Return the stored fingerprint, or None if absent / table missing."""
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (FINGERPRINT_KEY,)
            ).fetchone()
        return row["value"] if row else None
    except sqlite3.OperationalError:
        # Table or DB not initialized yet (e.g. fresh boot before init_db).
        return None


def record_fingerprint() -> None:
    """Persist the current fingerprint (upsert). Used when creating the collection."""
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (FINGERPRINT_KEY, current_fingerprint()),
        )
        conn.commit()


def clear_fingerprint() -> None:
    """Remove the stored fingerprint (used by the reset script)."""
    try:
        with _connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute("DELETE FROM settings WHERE key = ?", (FINGERPRINT_KEY,))
            conn.commit()
    except sqlite3.OperationalError:
        # Nothing to clear if the DB/table is absent.
        pass


def assert_fingerprint_ok(collection_exists: bool) -> None:
    """Raise RuntimeError if the collection exists but the fingerprint is missing
    or does not match the current embedding settings.

    Messages always contain ``embedding`` so ``classify_error`` maps them to
    ``EMBEDDING_ERROR`` rather than letting an upstream openai cause fall
    through to ``LLM_ERROR``.
    """
    if not collection_exists:
        return

    stored = stored_fingerprint()
    current = current_fingerprint()
    if stored is None:
        raise RuntimeError(
            "Embedding fingerprint missing: the Milvus collection exists but has no "
            "recorded embedding provider/model/dim. Pin the current settings with "
            "`python scripts/pin_embedding_fingerprint.py` (if the indexed data was "
            "produced by the current settings) or reset and reindex with "
            "`python scripts/reset_milvus_collection.py`."
        )
    if stored != current:
        raise RuntimeError(
            "Embedding fingerprint mismatch: the collection was indexed with a "
            "different embedding provider/model/dim than the current settings. "
            "Reset and reindex with `python scripts/reset_milvus_collection.py`."
        )
