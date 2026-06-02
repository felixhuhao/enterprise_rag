"""Best-effort token usage extraction for LangChain LLM responses."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def llm_model_name(llm: Any) -> str:
    """Extract a readable model name from a LangChain LLM wrapper."""
    for attr in ("model_name", "model", "model_id", "deployment_name"):
        value = getattr(llm, attr, None)
        if value:
            return str(value)
    return ""


def extract_llm_token_usage(source: Any, model_name: str = "") -> dict[str, Any]:
    """Extract token usage from LangChain messages/chunks when providers expose it."""
    usage: dict[str, Any] = {"model": model_name} if model_name else {}
    _merge_usage_fields(usage, getattr(source, "usage_metadata", None))

    response_metadata = getattr(source, "response_metadata", None)
    if isinstance(response_metadata, Mapping):
        if not usage.get("model"):
            usage["model"] = response_metadata.get("model_name") or response_metadata.get("model") or ""
        nested = (
            response_metadata.get("token_usage")
            or response_metadata.get("usage")
            or response_metadata.get("usage_metadata")
        )
        _merge_usage_fields(usage, nested)
        _merge_usage_fields(usage, response_metadata)

    return {str(k): v for k, v in usage.items() if v not in (None, "")}


def merge_token_usage(existing: Mapping[str, Any] | None, update: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge token usage snapshots; non-null values in update replace previous values."""
    merged = dict(existing or {})
    update = dict(update or {})
    if update.get("model"):
        merged["model"] = update["model"]
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = update.get(key)
        if value is not None:
            merged[key] = value
    return merged


def _merge_usage_fields(target: dict[str, Any], source: Any) -> None:
    if not isinstance(source, Mapping):
        return
    mappings = {
        "prompt_tokens": ("prompt_tokens", "input_tokens", "prompt_token_count", "input_token_count"),
        "completion_tokens": (
            "completion_tokens", "output_tokens", "completion_token_count", "output_token_count"
        ),
        "total_tokens": ("total_tokens", "total_token_count"),
    }
    for dest, names in mappings.items():
        for name in names:
            value = source.get(name)
            if value is not None:
                target[dest] = value
                break
