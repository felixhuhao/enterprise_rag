"""Tests for embedding / image-description provider config defaults."""

from app.config import Settings


class TestEmbeddingProviderConfig:
    def test_embedding_provider_defaults_to_local(self):
        assert Settings.model_fields["EMBEDDING_PROVIDER"].default == "local"

    def test_qwen_settings_default_empty_or_canonical(self):
        assert Settings.model_fields["QWEN_API_KEY"].default == ""
        assert (
            Settings.model_fields["QWEN_BASE_URL"].default
            == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )

    def test_remote_reliability_defaults(self):
        assert Settings.model_fields["EMBEDDING_TIMEOUT"].default == 30
        assert Settings.model_fields["EMBEDDING_MAX_RETRIES"].default == 2

    def test_image_description_provider_defaults_to_qwen(self):
        assert Settings.model_fields["IMAGE_DESCRIPTION_PROVIDER"].default == "qwen"
        assert Settings.model_fields["IMAGE_DESCRIPTION_MODEL"].default == "qwen3-vl-flash"


class TestEmbeddingDeviceForProviders:
    """embedding_device is only meaningful for local; remote reports 'remote'."""

    def test_local_keeps_configured_device(self):
        s = Settings(_env_file=(), EMBEDDING_DEVICE="cpu")
        assert s.EMBEDDING_DEVICE == "cpu"
