import pytest
from pydantic import ValidationError

from app.api.settings_api import _update_env_file
from app.errors import AppErrorCode, classify_error
from app.models.schemas import TokenUpdate


def test_update_env_file_rejects_newline_in_value(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("API_TOKEN=old\n", encoding="utf-8")

    with pytest.raises(ValueError):
        _update_env_file(env_path, "API_TOKEN", "good\nMALICIOUS=value")

    assert env_path.read_text(encoding="utf-8") == "API_TOKEN=old\n"


def test_token_update_rejects_oversized_token():
    with pytest.raises(ValidationError):
        TokenUpdate(token="x" * 513)


def test_openai_embedding_errors_classify_as_embedding_errors():
    assert classify_error(RuntimeError("OpenAI embeddings request failed")) == AppErrorCode.EMBEDDING_ERROR
