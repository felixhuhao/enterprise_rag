"""Tests for the image-description provider switch (zhipu vs qwen-VL)."""

import asyncio

import pytest

from app.config import settings


class _FakeChoiceMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeChoiceMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeChatCompletions:
    def __init__(self, owner):
        self._owner = owner

    async def create(self, **kwargs):
        self._owner.create_kwargs = kwargs
        return _FakeResponse("一张测试图片的描述")


class _FakeAsyncOpenAI:
    instances = []

    def __init__(self, **kwargs):
        self.constructor_kwargs = kwargs
        self.chat = types_simple_ns(completions=_FakeChatCompletions(self))
        _FakeAsyncOpenAI.instances.append(self)


def types_simple_ns(**kw):
    return type("_ns", (), kw)


@pytest.fixture
def fake_async_openai(monkeypatch):
    _FakeAsyncOpenAI.instances = []
    monkeypatch.setattr("app.rag.parsing.image_describer.AsyncOpenAI", _FakeAsyncOpenAI)
    return _FakeAsyncOpenAI


@pytest.fixture
def image_file(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")  # minimal PNG header
    return str(p)


class TestProviderSelection:
    def test_zhipu_uses_zhipu_credentials(self, monkeypatch, fake_async_openai, image_file):
        monkeypatch.setattr(settings, "IMAGE_DESCRIPTION_PROVIDER", "zhipu")
        monkeypatch.setattr(settings, "ZHIPU_API_KEY", "zhipu-key")
        monkeypatch.setattr(settings, "ZHIPU_BASE_URL", "https://zhipu.example/v1")
        monkeypatch.setattr(settings, "QWEN_API_KEY", "qwen-key")

        from app.rag.parsing.image_describer import describe_image

        asyncio.run(describe_image(image_file))

        ctor = fake_async_openai.instances[0].constructor_kwargs
        assert ctor["api_key"] == "zhipu-key"
        assert ctor["base_url"] == "https://zhipu.example/v1"

    def test_qwen_uses_qwen_credentials(self, monkeypatch, fake_async_openai, image_file):
        monkeypatch.setattr(settings, "IMAGE_DESCRIPTION_PROVIDER", "qwen")
        monkeypatch.setattr(settings, "ZHIPU_API_KEY", "zhipu-key")
        monkeypatch.setattr(settings, "QWEN_API_KEY", "qwen-key")
        monkeypatch.setattr(settings, "QWEN_BASE_URL", "https://qwen.example/v1")

        from app.rag.parsing.image_describer import describe_image

        asyncio.run(describe_image(image_file))

        ctor = fake_async_openai.instances[0].constructor_kwargs
        assert ctor["api_key"] == "qwen-key"
        assert ctor["base_url"] == "https://qwen.example/v1"

    def test_unknown_provider_fails_clearly(self, monkeypatch):
        monkeypatch.setattr(settings, "IMAGE_DESCRIPTION_PROVIDER", "qwne")

        from app.rag.parsing.image_describer import _vl_credentials

        with pytest.raises(RuntimeError, match="IMAGE_DESCRIPTION_PROVIDER"):
            _vl_credentials()

    def test_keeps_existing_image_message_shape(self, monkeypatch, fake_async_openai, image_file):
        monkeypatch.setattr(settings, "IMAGE_DESCRIPTION_PROVIDER", "qwen")
        monkeypatch.setattr(settings, "QWEN_API_KEY", "qwen-key")
        monkeypatch.setattr(settings, "IMAGE_DESCRIPTION_MODEL", "qwen3-vl-flash")

        from app.rag.parsing.image_describer import describe_image

        asyncio.run(describe_image(image_file))

        create_kwargs = fake_async_openai.instances[0].create_kwargs
        content = create_kwargs["messages"][0]["content"]
        assert content[0]["type"] == "image_url"
        assert "image_url" in content[0]
        assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert content[1]["type"] == "text"
        assert create_kwargs["model"] == "qwen3-vl-flash"
