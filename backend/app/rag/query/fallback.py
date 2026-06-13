"""Structured fallback state for query retrieval."""

from __future__ import annotations

from collections.abc import Mapping

from app.rag.query.state import QueryState

FALLBACK_TYPE_ENTITY_TO_GLOBAL = "entity_filter_to_global"
REASON_LOW_SCORE_OR_INSUFFICIENT_HITS = "low_score_or_insufficient_hits"
REASON_ENTITY_FALLBACK_DISABLED = "entity_fallback_disabled"


def empty_fallback_info() -> dict:
    return {
        "used": False,
        "blocked": False,
        "type": "",
        "reason": "",
        "original_filter": "",
    }


def fallback_used(original_filter: str | None, reason: str = REASON_LOW_SCORE_OR_INSUFFICIENT_HITS) -> dict:
    return {
        "used": True,
        "blocked": False,
        "type": FALLBACK_TYPE_ENTITY_TO_GLOBAL,
        "reason": reason,
        "original_filter": original_filter or "",
    }


def fallback_blocked(original_filter: str | None, reason: str = REASON_ENTITY_FALLBACK_DISABLED) -> dict:
    return {
        "used": False,
        "blocked": True,
        "type": FALLBACK_TYPE_ENTITY_TO_GLOBAL,
        "reason": reason,
        "original_filter": original_filter or "",
    }


def merge_fallback_info(existing: dict | None, update: dict | None) -> dict:
    """Keep the strongest fallback state: used > blocked > empty."""
    if not existing:
        existing = empty_fallback_info()
    if not update:
        return existing
    if update.get("used"):
        return update
    if existing.get("used"):
        return existing
    if update.get("blocked"):
        return update
    return existing


def state_fallback_info(state: QueryState) -> dict:
    info = state.get("fallback_info")
    if isinstance(info, dict):
        return info
    return empty_fallback_info()


def fallback_was_used(state: Mapping[str, object]) -> bool:
    """Return true when any current retrieval path used fallback."""
    info = state.get("fallback_info")
    if isinstance(info, dict) and info.get("used"):
        return True

    if _mode_has_fallback(state.get("search_mode")):
        return True
    if _mode_has_fallback(state.get("search_mode_hyde")):
        return True

    expanded_modes = state.get("search_modes_expanded")
    if isinstance(expanded_modes, list):
        return any(_mode_has_fallback(mode) for mode in expanded_modes)
    return False


def _mode_has_fallback(mode: object) -> bool:
    return isinstance(mode, str) and "fallback" in mode
