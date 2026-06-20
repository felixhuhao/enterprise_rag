"""Tests for provider-aware diagnostics (runtime-info + retrieval-test label)."""

import asyncio

from app.config import settings


class TestRuntimeInfo:
    def _get(self):
        from app.api.system_info import get_runtime_info
        return asyncio.run(get_runtime_info(current_user=None))

    def test_exposes_embedding_provider(self, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
        info = self._get()
        assert info["embedding_provider"] == "qwen"

    def test_embedding_device_is_remote_for_qwen(self, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
        info = self._get()
        assert info["embedding_device"] == "remote"

    def test_embedding_device_keeps_configured_for_local(self, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
        monkeypatch.setattr(settings, "EMBEDDING_DEVICE", "cpu")
        info = self._get()
        assert info["embedding_device"] == "cpu"

    def test_exposes_image_description_provider_and_model(self, monkeypatch):
        monkeypatch.setattr(settings, "IMAGE_DESCRIPTION_PROVIDER", "qwen")
        monkeypatch.setattr(settings, "IMAGE_DESCRIPTION_MODEL", "qwen3-vl-flash")
        info = self._get()
        assert info["image_description_provider"] == "qwen"
        assert info["image_description_model"] == "qwen3-vl-flash"


class TestEmbeddingModelLabel:
    def _label(self, settings_obj=None):
        from app.services.retrieval_test_formatting import embedding_model_label
        return embedding_model_label(settings_obj or settings)

    def test_local_prefixes_provider(self, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
        monkeypatch.setattr(settings, "EMBEDDING_MODEL_NAME", "bge-m3")
        assert self._label() == "local/bge-m3"

    def test_qwen_prefixes_provider(self, monkeypatch):
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
        monkeypatch.setattr(settings, "EMBEDDING_MODEL_NAME", "text-embedding-v4")
        assert self._label() == "qwen/text-embedding-v4"

    def test_no_path_fallback_for_qwen(self, monkeypatch):
        # Even with a stale EMBEDDING_MODEL_PATH, qwen label must not leak it.
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "qwen")
        monkeypatch.setattr(settings, "EMBEDDING_MODEL_NAME", "")
        monkeypatch.setattr(settings, "EMBEDDING_MODEL_PATH", "/models/embedding")
        label = self._label()
        assert "/models/embedding" not in label
        assert label.startswith("qwen/")
