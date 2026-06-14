import pytest

from app.errors import AppErrorCode, classify_error


def test_openai_embedding_errors_classify_as_embedding_errors():
    assert classify_error(RuntimeError("OpenAI embeddings request failed")) == AppErrorCode.EMBEDDING_ERROR


def test_chat_and_generic_timeout_do_not_imply_llm_error():
    assert classify_error(RuntimeError("chat history database timeout")) == AppErrorCode.UNKNOWN_ERROR
    assert classify_error(TimeoutError("operation timed out")) == AppErrorCode.UNKNOWN_ERROR


def test_wrapped_provider_errors_classify_from_exception_chain():
    OpenAITimeout = type("APITimeoutError", (Exception,), {"__module__": "openai"})
    wrapped = RuntimeError("request failed")
    wrapped.__cause__ = OpenAITimeout("request timed out")

    assert classify_error(wrapped) == AppErrorCode.LLM_ERROR


def test_milvus_timeout_classifies_as_milvus_error():
    MilvusException = type(
        "MilvusException",
        (Exception,),
        {"__module__": "pymilvus.exceptions"},
    )

    assert classify_error(MilvusException("timeout waiting for collection")) == AppErrorCode.MILVUS_ERROR
