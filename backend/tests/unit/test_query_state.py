import pytest

from app.rag.query.state import query_state_from_mapping, require_query


def test_require_query_trims_boundary_whitespace():
    assert require_query({"query": "  hello  "}) == "hello"


def test_query_state_from_mapping_rejects_conflicting_query_values():
    with pytest.raises(ValueError, match="Conflicting query values"):
        query_state_from_mapping({"query": "original"}, query="different")


def test_query_state_from_mapping_allows_matching_trimmed_query_values():
    state = query_state_from_mapping({"query": " original "}, query="original")
    assert state["query"] == "original"
