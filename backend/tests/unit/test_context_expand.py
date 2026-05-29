"""Unit tests for small-to-big context expansion."""

from unittest.mock import Mock

from app.rag.query.config import QueryConfig
from app.rag.query.context_expand import context_expand_node


def _cfg(**kwargs):
    return {"configurable": {"query_config": QueryConfig(**kwargs)}}


def _hit(chunk_id=2, part=2, content="anchor", source_type="text", section_title="S"):
    return {
        "chunk_id": chunk_id,
        "document_id": "doc-1",
        "section_title": section_title,
        "source_type": source_type,
        "part": part,
        "content": content,
        "retrieval_paths": ["Hybrid"],
        "retrieval_path": "Hybrid",
    }


def _neighbor(chunk_id, part, content):
    return {
        "chunk_id": chunk_id,
        "document_id": "doc-1",
        "section_title": "S",
        "source_type": "text",
        "part": part,
        "content": content,
    }


def _patch_query(monkeypatch, rows):
    mock = Mock(return_value=rows)
    monkeypatch.setattr("app.rag.query.context_expand.client.query", mock)
    return mock


def test_disabled_passthrough(monkeypatch):
    query = _patch_query(monkeypatch, [_neighbor(1, 1, "left")])
    results = [_hit()]

    out = context_expand_node({"search_results": results}, _cfg(use_context_expand=False))

    assert out["search_results"] is results
    query.assert_not_called()


def test_empty_results():
    out = context_expand_node({"search_results": []}, _cfg())

    assert out["search_results"] == []


def test_window_zero_does_not_query_neighbors(monkeypatch):
    query = _patch_query(monkeypatch, [_neighbor(1, 1, "left")])
    results = [_hit()]

    out = context_expand_node({"search_results": results}, _cfg(context_expand_window=0))

    assert out["search_results"] is results
    query.assert_not_called()


def test_non_text_skipped(monkeypatch):
    query = _patch_query(monkeypatch, [_neighbor(1, 1, "left")])

    out = context_expand_node({"search_results": [_hit(source_type="table_full")]}, _cfg())

    assert out["search_results"][0]["content"] == "anchor"
    query.assert_not_called()


def test_part_none_skipped(monkeypatch):
    query = _patch_query(monkeypatch, [_neighbor(1, 1, "left")])

    out = context_expand_node({"search_results": [_hit(part=None)]}, _cfg())

    assert out["search_results"][0]["content"] == "anchor"
    query.assert_not_called()


def test_empty_section_skipped(monkeypatch):
    query = _patch_query(monkeypatch, [_neighbor(1, 1, "left")])

    out = context_expand_node({"search_results": [_hit(section_title="")]}, _cfg())

    assert out["search_results"][0]["content"] == "anchor"
    query.assert_not_called()


def test_left_neighbor_prepended(monkeypatch):
    _patch_query(monkeypatch, [_neighbor(1, 1, "left")])

    out = context_expand_node({"search_results": [_hit(part=2)]}, _cfg())

    assert out["search_results"][0]["content"].startswith("left\n\nanchor")


def test_right_neighbor_appended(monkeypatch):
    _patch_query(monkeypatch, [_neighbor(3, 2, "right")])

    out = context_expand_node({"search_results": [_hit(part=1)]}, _cfg())

    assert out["search_results"][0]["content"].endswith("anchor\n\nright")


def test_both_sides_expand_in_part_order(monkeypatch):
    _patch_query(monkeypatch, [
        _neighbor(3, 3, "right"),
        _neighbor(1, 1, "left"),
    ])

    out = context_expand_node({"search_results": [_hit(part=2)]}, _cfg())
    content = out["search_results"][0]["content"]

    assert content.index("left") < content.index("anchor") < content.index("right")


def test_max_chars_truncates_merged_content(monkeypatch):
    _patch_query(monkeypatch, [
        _neighbor(1, 1, "L" * 200),
        _neighbor(3, 3, "R" * 200),
    ])

    out = context_expand_node(
        {"search_results": [_hit(part=2, content="A" * 400)]},
        _cfg(context_expand_max_chars=500),
    )

    assert len(out["search_results"][0]["content"]) == 500
    assert "A" * 400 in out["search_results"][0]["content"]


def test_anchor_neighbor_is_deduped(monkeypatch):
    _patch_query(monkeypatch, [_neighbor(3, 3, "right")])
    anchor_2 = _hit(chunk_id=2, part=2, content="anchor-2")
    anchor_3 = _hit(chunk_id=3, part=3, content="anchor-3")

    out = context_expand_node({"search_results": [anchor_2, anchor_3]}, _cfg())

    assert "right" not in out["search_results"][0]["content"]


def test_retrieval_paths_mark_context_expand(monkeypatch):
    _patch_query(monkeypatch, [_neighbor(1, 1, "left")])

    out = context_expand_node({"search_results": [_hit(part=2)]}, _cfg())
    row = out["search_results"][0]

    assert "context_expand" in row["retrieval_paths"]
    assert row["context_expanded_chunk_ids"] == [1]
    assert row["context_expand_parts"] == [1]


def test_original_over_limit_does_not_query_neighbors(monkeypatch):
    query = _patch_query(monkeypatch, [_neighbor(1, 1, "left")])

    out = context_expand_node(
        {"search_results": [_hit(part=2, content="A" * 501)]},
        _cfg(context_expand_max_chars=500),
    )

    assert out["search_results"][0]["content"] == "A" * 501
    query.assert_not_called()


def test_query_exception_keeps_anchor(monkeypatch):
    mock = Mock(side_effect=RuntimeError("milvus unavailable"))
    monkeypatch.setattr("app.rag.query.context_expand.client.query", mock)

    out = context_expand_node({"search_results": [_hit(part=2)]}, _cfg())

    assert out["search_results"][0]["content"] == "anchor"
