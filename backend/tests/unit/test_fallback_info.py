"""Unit tests for structured fallback state."""

from app.rag.query.fallback import (
    empty_fallback_info,
    fallback_blocked,
    fallback_used,
    merge_fallback_info,
)


def test_empty_fallback_info_shape():
    info = empty_fallback_info()
    assert info == {
        "used": False,
        "blocked": False,
        "type": "",
        "reason": "",
        "original_filter": "",
    }


def test_used_beats_blocked_when_merging():
    used = fallback_used('(entity_name == "实体A")')
    blocked = fallback_blocked('(entity_name == "实体A")')

    assert merge_fallback_info(blocked, used) == used
    assert merge_fallback_info(used, blocked) == used


def test_blocked_beats_empty_when_merging():
    blocked = fallback_blocked('(entity_name == "实体A")')
    assert merge_fallback_info(empty_fallback_info(), blocked) == blocked
