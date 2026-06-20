"""Tests for embedding fingerprint integration into general_milvus.

general_milvus instantiates a MilvusClient at import time, which connects
eagerly. To run without a live Milvus, these tests inject a fake ``pymilvus``
module and re-import general_milvus fresh against the fake client.
"""

import sqlite3
import sys
import types

import pytest

from app.config import settings


def _build_fake_pymilvus():
    """A minimal stand-in for pymilvus exposing the symbols general_milvus uses."""

    class DataType:
        INT64 = "INT64"
        VARCHAR = "VARCHAR"
        FLOAT_VECTOR = "FLOAT_VECTOR"
        SPARSE_FLOAT_VECTOR = "SPARSE_FLOAT_VECTOR"
        INT8 = "INT8"

    class FunctionType:
        BM25 = "BM25"

    class Function:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _Schema:
        def add_field(self, **kwargs):
            return self

        def add_function(self, fn):
            return self

    class _IndexParams:
        def add_index(self, **kwargs):
            return self

    class FakeMilvusClient:
        def __init__(self, **kwargs):
            self.has_collection_result = False
            self.created = False

        def has_collection(self, collection_name):
            return self.has_collection_result

        def create_collection(self, **kwargs):
            self.created = True

        def create_schema(self):
            return _Schema()

        def prepare_index_params(self):
            return _IndexParams()

    mod = types.ModuleType("pymilvus")
    mod.DataType = DataType
    mod.FunctionType = FunctionType
    mod.Function = Function
    mod.MilvusClient = FakeMilvusClient
    return mod, FakeMilvusClient


@pytest.fixture
def gm_with_fake_client(monkeypatch, tmp_path):
    """Import general_milvus against a fake pymilvus + temp fingerprint DB."""
    db_path = tmp_path / "fp.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))

    fake_mod, fake_client_cls = _build_fake_pymilvus()
    # Replace pymilvus with the fake and drop the cached general_milvus so it
    # re-imports against the fake. monkeypatch restores sys.modules on teardown.
    saved_gm_pkg = sys.modules.get("app.rag.vectorstores")
    monkeypatch.setitem(sys.modules, "pymilvus", fake_mod)
    for key in [k for k in list(sys.modules) if k.startswith("app.rag.vectorstores.general_milvus")]:
        monkeypatch.delitem(sys.modules, key, raising=False)
    # vectorstores package __init__ may or may not exist; drop it so reimport is clean.
    if saved_gm_pkg is None and "app.rag.vectorstores" in sys.modules:
        monkeypatch.delitem(sys.modules, "app.rag.vectorstores", raising=False)

    import importlib

    gm = importlib.import_module("app.rag.vectorstores.general_milvus")

    yield gm, fake_client_cls

    # monkeypatch restores sys.modules automatically on teardown.


# ---------------------------------------------------------------------------
# verify_embedding_fingerprint wiring
# ---------------------------------------------------------------------------


class TestVerifyWiring:
    def test_noop_when_collection_absent(self, gm_with_fake_client):
        gm, _ = gm_with_fake_client
        gm.client.has_collection_result = False
        # Must not raise.
        gm.verify_embedding_fingerprint()

    def test_blocks_when_collection_exists_without_fingerprint(self, gm_with_fake_client):
        gm, _ = gm_with_fake_client
        gm.client.has_collection_result = True
        with pytest.raises(RuntimeError, match="(?i)fingerprint"):
            gm.verify_embedding_fingerprint()

    def test_passes_when_fingerprint_matches(self, gm_with_fake_client, monkeypatch):
        gm, _ = gm_with_fake_client
        gm.client.has_collection_result = True
        from app.rag.vectorstores import embedding_fingerprint as fp

        fp.record_fingerprint()
        gm.verify_embedding_fingerprint()

    def test_blocks_on_mismatch(self, gm_with_fake_client, monkeypatch):
        gm, _ = gm_with_fake_client
        gm.client.has_collection_result = True
        from app.rag.vectorstores import embedding_fingerprint as fp

        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
        fp.record_fingerprint()
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
        with pytest.raises(RuntimeError, match="(?i)mismatch|reset"):
            gm.verify_embedding_fingerprint()


class TestEnsureCollectionRecordsFingerprint:
    def test_create_records_fingerprint(self, gm_with_fake_client):
        gm, _ = gm_with_fake_client
        from app.rag.vectorstores import embedding_fingerprint as fp

        gm.client.has_collection_result = False  # collection absent → create path
        gm.ensure_collection()

        assert gm.client.created is True
        assert fp.stored_fingerprint() == fp.current_fingerprint()

    def test_existing_collection_does_not_overwrite(self, gm_with_fake_client, monkeypatch):
        gm, _ = gm_with_fake_client
        from app.rag.vectorstores import embedding_fingerprint as fp

        gm.client.has_collection_result = True
        # Pre-record a fingerprint for a different provider.
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
        fp.record_fingerprint()
        original = fp.stored_fingerprint()

        # ensure_collection early-returns; must NOT rewrite the fingerprint.
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
        gm.ensure_collection()
        assert fp.stored_fingerprint() == original


class TestUpsertVerifiesFingerprint:
    def test_upsert_blocks_when_collection_has_no_fingerprint(self, gm_with_fake_client):
        gm, _ = gm_with_fake_client
        gm.client.has_collection_result = True  # exists, no fingerprint → strict block
        with pytest.raises(RuntimeError, match="(?i)fingerprint"):
            gm.upsert_document_chunks("doc-1", [{"content": "x", "dense": [0.1]}])
