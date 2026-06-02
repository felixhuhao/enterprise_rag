"""Unit tests for query chat retrieved chunk snapshots."""

import json
from types import SimpleNamespace

from app.api.query_chat import (
    _build_retrieved_chunks,
    _extract_llm_chunk_token_usage,
    _merge_token_usage,
)


def test_retrieved_chunks_include_chunk_key_without_full_content():
    payload = _build_retrieved_chunks([
        {
            "chunk_id": 1,
            "chunk_key": "ck_abc",
            "document_id": "doc-1",
            "file_title": "a.pdf",
            "content": "完整内容" * 100,
            "keywords": ["VP审批"],
            "structured_tags": ["amount_threshold", "approval_rule"],
            "score": 0.9,
        }
    ])

    rows = json.loads(payload)

    assert rows[0]["chunk_key"] == "ck_abc"
    assert rows[0]["keywords"] == ["VP审批"]
    assert rows[0]["structured_tags"] == ["amount_threshold", "approval_rule"]
    assert rows[0]["content_preview"]
    assert "content" not in rows[0]
    assert "search_text" not in rows[0]


def test_extract_llm_chunk_token_usage_from_usage_metadata():
    chunk = SimpleNamespace(
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        },
        response_metadata={},
    )

    usage = _extract_llm_chunk_token_usage(chunk, "qwen-plus")

    assert usage == {
        "model": "qwen-plus",
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }


def test_extract_llm_chunk_token_usage_from_response_metadata():
    chunk = SimpleNamespace(
        usage_metadata=None,
        response_metadata={
            "model_name": "deepseek-chat",
            "token_usage": {
                "prompt_tokens": 80,
                "completion_tokens": 10,
                "total_tokens": 90,
            },
        },
    )

    usage = _extract_llm_chunk_token_usage(chunk)

    assert usage["model"] == "deepseek-chat"
    assert usage["prompt_tokens"] == 80
    assert usage["completion_tokens"] == 10
    assert usage["total_tokens"] == 90


def test_merge_token_usage_last_metadata_wins_without_summing_chunks():
    existing = {"model": "qwen-plus", "prompt_tokens": 10}
    update = {"completion_tokens": 20, "total_tokens": 30}

    merged = _merge_token_usage(existing, update)

    assert merged == {
        "model": "qwen-plus",
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
    }
