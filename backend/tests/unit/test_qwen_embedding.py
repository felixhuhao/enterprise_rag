"""Unit tests for the embedding provider switch (local BGE-M3 vs remote Qwen)."""

import sys

import pytest

from app.config import settings
from app.errors import AppErrorCode, classify_error


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeEmbeddingItem:
    def __init__(self, index, vector):
        self.index = index
        self.embedding = vector


class _FakeCreateResponse:
    def __init__(self, data):
        self.data = data


class _FakeEmbeddings:
    def __init__(self, owner):
        self._owner = owner

    def create(self, **kwargs):
        self._owner.create_kwargs = kwargs
        batch = kwargs["input"]
        responder = _FakeOpenAI.responder
        if responder is not None:
            return responder(batch, kwargs)
        return _FakeCreateResponse(
            [_FakeEmbeddingItem(i, [float(i), float(i) + 0.1]) for i in range(len(batch))]
        )


class _FakeOpenAI:
    """Stand-in for openai.OpenAI; records construction kwargs.

    A class-level ``responder`` lets tests steer create() output without having
    to poke at a specific instance (the provider builds the client lazily).
    """

    #: when set, called as responder(batch, kwargs) -> _FakeCreateResponse | raises
    responder = None
    instances = []

    def __init__(self, **kwargs):
        self.constructor_kwargs = kwargs
        self.create_kwargs = None
        self.embeddings = _FakeEmbeddings(self)
        _FakeOpenAI.instances.append(self)


@pytest.fixture
def fake_openai(monkeypatch):
    _FakeOpenAI.instances = []
    _FakeOpenAI.responder = None
    monkeypatch.setattr("app.rag.embeddings.dense_embedding.OpenAI", _FakeOpenAI)
    return _FakeOpenAI


@pytest.fixture
def qwen_settings(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
    monkeypatch.setattr(settings, "QWEN_API_KEY", "sk-test-qwen")
    monkeypatch.setattr(settings, "QWEN_BASE_URL", "https://dashscope.example/v1")
    monkeypatch.setattr(settings, "EMBEDDING_MODEL_NAME", "text-embedding-v4")
    monkeypatch.setattr(settings, "EMBEDDING_DIM", 1024)
    monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 10)
    monkeypatch.setattr(settings, "EMBEDDING_TIMEOUT", 30)
    monkeypatch.setattr(settings, "EMBEDDING_MAX_RETRIES", 2)


# ---------------------------------------------------------------------------
# Factory selection
# ---------------------------------------------------------------------------


class TestFactorySelection:
    def test_selects_qwen_when_provider_qwen(self, qwen_settings):
        from app.rag.embeddings.dense_embedding import QwenDenseEmbedding, get_dense_embedding

        obj = get_dense_embedding()
        assert isinstance(obj, QwenDenseEmbedding)

    def test_selects_local_by_default(self, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
        from app.rag.embeddings.dense_embedding import LocalBgeDenseEmbedding, get_dense_embedding

        obj = get_dense_embedding()
        assert isinstance(obj, LocalBgeDenseEmbedding)

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "bogus")
        from app.rag.embeddings.dense_embedding import get_dense_embedding

        with pytest.raises(RuntimeError, match="(?i)embedding"):
            get_dense_embedding()


# ---------------------------------------------------------------------------
# Qwen provider behavior
# ---------------------------------------------------------------------------


class TestQwenEmbedDocuments:
    def test_uses_embeddings_create_endpoint(self, qwen_settings, fake_openai):
        from app.rag.embeddings.dense_embedding import QwenDenseEmbedding

        prov = QwenDenseEmbedding()
        prov.embed_documents(["hello", "world"])

        assert fake_openai.instances, "OpenAI client must be constructed"
        kwargs = fake_openai.instances[0].create_kwargs
        assert set(["model", "input", "dimensions", "encoding_format"]).issubset(kwargs.keys())

    def test_passes_model_input_dimensions_encoding_format(self, qwen_settings, fake_openai):
        from app.rag.embeddings.dense_embedding import QwenDenseEmbedding

        prov = QwenDenseEmbedding()
        prov.embed_documents(["alpha", "beta"])

        kwargs = fake_openai.instances[0].create_kwargs
        assert kwargs["model"] == "text-embedding-v4"
        assert kwargs["input"] == ["alpha", "beta"]
        assert kwargs["dimensions"] == 1024
        assert kwargs["encoding_format"] == "float"

    def test_preserves_output_order_via_response_index(self, qwen_settings, fake_openai):
        from app.rag.embeddings.dense_embedding import QwenDenseEmbedding

        # API returns items out of order: index 1 then 0, with distinct vectors.
        fake_openai.responder = lambda batch, kwargs: _FakeCreateResponse(
            [_FakeEmbeddingItem(1, [0.9, 0.9]), _FakeEmbeddingItem(0, [0.1, 0.1])]
        )

        prov = QwenDenseEmbedding()
        out = prov.embed_documents(["first", "second"])
        assert out[0] == [0.1, 0.1]  # "first" → index 0
        assert out[1] == [0.9, 0.9]  # "second" → index 1

    def test_rejects_missing_qwen_api_key(self, qwen_settings, fake_openai, monkeypatch):
        monkeypatch.setattr(settings, "QWEN_API_KEY", "")
        from app.rag.embeddings.dense_embedding import QwenDenseEmbedding

        prov = QwenDenseEmbedding()
        with pytest.raises(RuntimeError, match="(?i)qwen_api_key"):
            prov.embed_documents(["x"])

    def test_rejects_batch_size_above_10(self, qwen_settings, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 20)
        from app.rag.embeddings.dense_embedding import QwenDenseEmbedding

        with pytest.raises(RuntimeError, match="(?i)batch"):
            QwenDenseEmbedding()

    def test_rejects_chunk_size_above_10(self, qwen_settings, fake_openai):
        from app.rag.embeddings.dense_embedding import QwenDenseEmbedding

        prov = QwenDenseEmbedding()
        with pytest.raises(RuntimeError, match="(?i)batch"):
            prov.embed_documents(["x"], chunk_size=20)

    def test_passes_timeout_and_max_retries_to_openai_client(self, qwen_settings, fake_openai):
        from app.rag.embeddings.dense_embedding import QwenDenseEmbedding

        prov = QwenDenseEmbedding()
        prov.embed_documents(["x"])

        ctor = fake_openai.instances[0].constructor_kwargs
        assert ctor["timeout"] == 30
        assert ctor["max_retries"] == 2
        assert ctor["api_key"] == "sk-test-qwen"
        assert ctor["base_url"] == "https://dashscope.example/v1"

    def test_wraps_openai_exception_as_embedding_error(self, qwen_settings, fake_openai):
        import httpx
        import openai

        from app.rag.embeddings.dense_embedding import QwenDenseEmbedding

        resp = httpx.Response(429, request=httpx.Request("POST", "https://x/v1/embeddings"))
        rate_err = openai.RateLimitError("rate limited", response=resp, body=None)
        fake_openai.responder = lambda batch, kwargs: (_ for _ in ()).throw(rate_err)

        prov = QwenDenseEmbedding()
        with pytest.raises(RuntimeError) as exc_info:
            prov.embed_documents(["x"])

        # Must classify as EMBEDDING_ERROR, NOT LLM_ERROR, despite the openai cause.
        assert classify_error(exc_info.value) is AppErrorCode.EMBEDDING_ERROR
        # The raw openai exception, if it had escaped unwrapped, would be LLM_ERROR:
        assert classify_error(rate_err) is AppErrorCode.LLM_ERROR

    def test_batches_by_embedding_batch_size(self, qwen_settings, fake_openai, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 2)
        from app.rag.embeddings.dense_embedding import QwenDenseEmbedding

        calls = []

        def responder(batch, kwargs):
            calls.append(list(batch))
            return _FakeCreateResponse([_FakeEmbeddingItem(i, [0.0, 0.0]) for i in range(len(batch))])

        fake_openai.responder = responder
        prov = QwenDenseEmbedding()
        prov.embed_documents(["a", "b", "c", "d", "e"])

        assert calls == [["a", "b"], ["c", "d"], ["e"]]

    def test_empty_input_returns_empty(self, qwen_settings, fake_openai):
        from app.rag.embeddings.dense_embedding import QwenDenseEmbedding

        prov = QwenDenseEmbedding()
        assert prov.embed_documents([]) == []


class TestQwenEmbedQuery:
    def test_returns_single_vector(self, qwen_settings, fake_openai):
        from app.rag.embeddings.dense_embedding import QwenDenseEmbedding

        prov = QwenDenseEmbedding()
        vec = prov.embed_query("solo")
        assert isinstance(vec, list)
        assert len(vec) == 2  # fake returns 2-dim vectors


# ---------------------------------------------------------------------------
# Local provider + lazy heavy imports
# ---------------------------------------------------------------------------


class TestLocalProviderUnchanged:
    def test_module_level_dense_embedding_is_local_by_default(self, monkeypatch):
        # The module-level singleton is selected at import time from settings.
        # Force a fresh import under the default provider to avoid test-order
        # coupling with qwen-settings tests in the same session.
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
        for mod_name in [m for m in list(sys.modules) if m == "app.rag.embeddings.dense_embedding"]:
            monkeypatch.delitem(sys.modules, mod_name, raising=False)
        import importlib

        mod = importlib.import_module("app.rag.embeddings.dense_embedding")
        assert isinstance(mod.dense_embedding, mod.LocalBgeDenseEmbedding)

    def test_qwen_provider_does_not_import_torch(self, qwen_settings, fake_openai, monkeypatch):
        # Selecting the qwen provider must never pull in torch/FlagEmbedding.
        # Actively drop them (plus the cached module) so the assertion is
        # deterministic even if an earlier test loaded the local model.
        for mod_name in [m for m in list(sys.modules) if m == "app.rag.embeddings.dense_embedding"]:
            monkeypatch.delitem(sys.modules, mod_name, raising=False)
        for heavy in ("torch", "FlagEmbedding"):
            if heavy in sys.modules:
                monkeypatch.delitem(sys.modules, heavy, raising=False)

        import importlib

        mod = importlib.import_module("app.rag.embeddings.dense_embedding")
        prov = mod.get_dense_embedding()
        assert isinstance(prov, mod.QwenDenseEmbedding)
        assert "torch" not in sys.modules
        assert "FlagEmbedding" not in sys.modules
