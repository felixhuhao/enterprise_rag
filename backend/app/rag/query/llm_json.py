"""Shared helpers for tolerant LLM JSON extraction."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_llm_json(raw: str) -> Any | None:
    """Parse direct, fenced, or lightly wrapped JSON from an LLM response."""
    if not isinstance(raw, str) or not raw.strip():
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass

    stripped = re.sub(r"^[^{[]*", "", raw)
    stripped = re.sub(r"[^}\]]*$", "", stripped)
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def parse_llm_json_object(raw: str) -> dict | None:
    """Parse an LLM response and require a JSON object result."""
    parsed = parse_llm_json(raw)
    return parsed if isinstance(parsed, dict) else None
