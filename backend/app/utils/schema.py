"""Small schema-boundary helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def ensure_dict(value: Any) -> dict[str, Any]:
    """Return a plain dict for mapping-like values, otherwise an empty dict."""
    return dict(value) if isinstance(value, Mapping) else {}
