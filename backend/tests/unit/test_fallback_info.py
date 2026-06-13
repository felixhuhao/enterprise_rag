"""Unit tests for structured fallback state."""

from app.rag.query.fallback import (
    empty_fallback_info,
    fallback_blocked,
    fallback_used,
    fallback_was_used,
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


def test_fallback_was_used_reads_structured_info():
    assert fallback_was_used({"fallback_info": fallback_used("entity_name == 'A'")}) is True
    assert fallback_was_used({"fallback_info": fallback_blocked("entity_name == 'A'")}) is False


def test_fallback_was_used_preserves_legacy_mode_detection():
    assert fallback_was_used({"search_mode": "hybrid_filtered_fallback_unfiltered"}) is True
    assert fallback_was_used({"search_mode_hyde": "hyde_filtered_fallback_unfiltered"}) is True
    assert fallback_was_used({"search_modes_expanded": ["hybrid", "expanded_fallback"]}) is True
    assert fallback_was_used({"search_mode": "hybrid", "search_modes_expanded": ["expanded"]}) is False
