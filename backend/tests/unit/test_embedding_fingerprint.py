"""Tests for the embedding fingerprint guard (vector-space safety).

The fingerprint module is a sync SQLite KV helper; verify() combines the stored
fingerprint with collection-existence so callers don't need a DB or Milvus mock
to exercise the core guard logic.
"""

import json
import sqlite3

import pytest

from app.config import settings
from app.errors import AppErrorCode, classify_error


@pytest.fixture
def fp_db(tmp_path, monkeypatch):
    """Point the fingerprint module at a fresh temp SQLite DB with the settings table."""
    db_path = tmp_path / "fp.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))
    return db_path


def _fp():
    from app.rag.vectorstores import embedding_fingerprint as fp

    return fp


# ---------------------------------------------------------------------------
# current_fingerprint
# ---------------------------------------------------------------------------


class TestCurrentFingerprint:
    def test_reflects_provider_model_dim(self, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
        monkeypatch.setattr(settings, "EMBEDDING_MODEL_NAME", "text-embedding-v4")
        monkeypatch.setattr(settings, "EMBEDDING_DIM", 1024)
        fp = _fp()
        parsed = json.loads(fp.current_fingerprint())
        assert parsed == {"provider": "qwen", "model": "text-embedding-v4", "dim": 1024}

    def test_changes_when_provider_changes(self, monkeypatch):
        fp = _fp()
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
        local = fp.current_fingerprint()
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
        qwen = fp.current_fingerprint()
        assert local != qwen


# ---------------------------------------------------------------------------
# SQLite read / write / clear
# ---------------------------------------------------------------------------


class TestStoredRecordClear:
    def test_stored_returns_none_when_nothing_recorded(self, fp_db):
        fp = _fp()
        assert fp.stored_fingerprint() is None

    def test_record_then_stored_returns_it(self, fp_db, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
        monkeypatch.setattr(settings, "EMBEDDING_MODEL_NAME", "text-embedding-v4")
        monkeypatch.setattr(settings, "EMBEDDING_DIM", 1024)
        fp = _fp()
        fp.record_fingerprint()
        assert fp.stored_fingerprint() == fp.current_fingerprint()

    def test_record_is_idempotent_upsert(self, fp_db, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
        fp = _fp()
        fp.record_fingerprint()
        fp.record_fingerprint()  # second upsert must not error
        assert fp.stored_fingerprint() == fp.current_fingerprint()

    def test_clear_removes_fingerprint(self, fp_db, monkeypatch):
        fp = _fp()
        fp.record_fingerprint()
        assert fp.stored_fingerprint() is not None
        fp.clear_fingerprint()
        assert fp.stored_fingerprint() is None

    def test_stored_returns_none_when_table_missing(self, tmp_path, monkeypatch):
        # No settings table created → read must degrade gracefully to None.
        db_path = tmp_path / "empty.db"
        sqlite3.connect(db_path).close()
        monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))
        fp = _fp()
        assert fp.stored_fingerprint() is None


# ---------------------------------------------------------------------------
# assert_fingerprint_ok (guard logic)
# ---------------------------------------------------------------------------


class TestAssertFingerprintOk:
    def test_passes_when_collection_absent(self, fp_db):
        # No collection → nothing to protect; guard is a no-op.
        _fp().assert_fingerprint_ok(collection_exists=False)

    def test_passes_when_fingerprint_matches(self, fp_db, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
        fp = _fp()
        fp.record_fingerprint()
        fp.assert_fingerprint_ok(collection_exists=True)

    def test_blocks_when_collection_exists_but_no_fingerprint(self, fp_db):
        # Strict default: existing collection with no stored fingerprint is blocked.
        fp = _fp()
        with pytest.raises(RuntimeError) as exc_info:
            fp.assert_fingerprint_ok(collection_exists=True)
        msg = str(exc_info.value).lower()
        assert "fingerprint" in msg
        # Must classify as EMBEDDING_ERROR for consistent UX.
        assert classify_error(exc_info.value) is AppErrorCode.EMBEDDING_ERROR

    def test_blocks_on_provider_mismatch(self, fp_db, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
        fp = _fp()
        fp.record_fingerprint()
        # Now switch provider without reindex.
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
        with pytest.raises(RuntimeError, match="(?i)mismatch|reset"):
            fp.assert_fingerprint_ok(collection_exists=True)

    def test_blocks_on_dim_mismatch(self, fp_db, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_DIM", 1024)
        fp = _fp()
        fp.record_fingerprint()
        monkeypatch.setattr(settings, "EMBEDDING_DIM", 768)
        with pytest.raises(RuntimeError, match="(?i)mismatch|reset"):
            fp.assert_fingerprint_ok(collection_exists=True)
