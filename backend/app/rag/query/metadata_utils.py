"""Helpers for retrieval metadata fields stored as JSON strings."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def parse_json_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON list metadata", exc_info=True)
            return []
    return []
