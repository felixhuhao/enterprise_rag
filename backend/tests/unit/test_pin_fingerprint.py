"""Tests for the pin_embedding_fingerprint script core logic."""

import sqlite3

import pytest

from app.config import settings


@pytest.fixture
def fp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "fp.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))
    return db_path


def _pin_mod(monkeypatch, exists: bool):
    import importlib

    mod = importlib.import_module("scripts.pin_embedding_fingerprint")
    monkeypatch.setattr(mod, "collection_exists", lambda: exists)
    return mod


class TestPin:
    def test_refuses_when_collection_absent(self, fp_db, monkeypatch):
        mod = _pin_mod(monkeypatch, exists=False)
        with pytest.raises(RuntimeError, match="(?i)does not exist"):
            mod.pin()

    def test_pins_when_collection_exists_no_prior(self, fp_db, monkeypatch):
        from app.rag.vectorstores import embedding_fingerprint as fp

        mod = _pin_mod(monkeypatch, exists=True)
        assert fp.stored_fingerprint() is None

        msg = mod.pin()

        assert "Pinned" in msg
        assert fp.stored_fingerprint() == fp.current_fingerprint()

    def test_refuses_to_overwrite_mismatched_without_force(self, fp_db, monkeypatch):
        from app.rag.vectorstores import embedding_fingerprint as fp

        # Pre-store a fingerprint for a different provider.
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
        fp.record_fingerprint()
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")

        mod = _pin_mod(monkeypatch, exists=True)
        with pytest.raises(RuntimeError, match="(?i)mismatch|reset"):
            mod.pin()

    def test_yes_mode_must_not_overwrite_mismatched(self, fp_db, monkeypatch):
        from app.rag.vectorstores import embedding_fingerprint as fp

        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
        fp.record_fingerprint()
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")

        mod = _pin_mod(monkeypatch, exists=True)
        with pytest.raises(RuntimeError, match="(?i)mismatch|reset"):
            mod.pin()
