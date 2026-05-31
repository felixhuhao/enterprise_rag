from app.rag.query.diversify_context import diversify_context_node


def _cfg(flavor="recall"):
    return {"configurable": {"query_config": {"retrieval_flavor": flavor}}}


def _state(flavor="recall", final_context_k=3, candidates=None):
    return {
        "query": "q",
        "query_plan": {
            "retrieval_flavor": flavor,
            "budget": {"final_context_k": final_context_k},
        },
        "rerank_candidates": candidates or [],
    }


def _doc(doc_id, chunk, score, section="s", title=None):
    return {
        "document_id": doc_id,
        "chunk_key": chunk,
        "file_title": title or f"{doc_id}.md",
        "section_title": section,
        "source_type": "text",
        "score": score,
        "rerank": {"final_score": score},
        "retrieval_paths": ["Hybrid"],
    }


def test_dedupes_chunk_key_for_all_flavors():
    candidates = [
        _doc("a", "same", 1.0),
        _doc("b", "same", 0.9),
        _doc("c", "c1", 0.8),
    ]

    out = diversify_context_node(_state("balanced", 3, candidates), _cfg("balanced"))

    assert [doc["chunk_key"] for doc in out["search_results"]] == ["same", "c1"]


def test_balanced_keeps_existing_rerank_window():
    candidates = [
        _doc("a", "a1", 1.0),
        _doc("b", "b1", 0.9),
        _doc("c", "c1", 0.8),
    ]
    state = _state("balanced", 3, candidates)
    state["search_results"] = candidates[:1]

    out = diversify_context_node(state, _cfg("balanced"))

    assert [doc["chunk_key"] for doc in out["search_results"]] == ["a1"]


def test_recall_prioritizes_document_coverage_before_duplicates():
    candidates = [
        _doc("a", "a1", 1.0, "s1"),
        _doc("a", "a2", 0.99, "s1"),
        _doc("a", "a3", 0.98, "s2"),
        _doc("b", "b1", 0.6, "s1"),
        _doc("c", "c1", 0.5, "s1"),
    ]

    out = diversify_context_node(_state("recall", 3, candidates), _cfg("recall"))

    assert [doc["document_id"] for doc in out["search_results"]] == ["a", "b", "c"]


def test_recall_avoids_same_section_until_coverage_is_filled():
    candidates = [
        _doc("a", "a1", 1.0, "s1"),
        _doc("b", "b1", 0.9, "s1"),
        _doc("a", "a2", 0.8, "s1"),
        _doc("a", "a3", 0.7, "s2"),
    ]

    out = diversify_context_node(_state("recall", 3, candidates), _cfg("recall"))

    assert [doc["chunk_key"] for doc in out["search_results"]] == ["a1", "b1", "a3"]


def test_recall_does_not_fill_with_low_confidence_noise():
    candidates = [
        _doc("a", "a1", 1.0, "s1"),
        _doc("b", "b1", 0.7, "s1"),
        _doc("c", "c1", 0.49, "s1"),
        _doc("d", "d1", 0.1, "s1"),
    ]

    out = diversify_context_node(_state("recall", 4, candidates), _cfg("recall"))

    assert [doc["chunk_key"] for doc in out["search_results"]] == ["a1", "b1"]


def test_updates_debug():
    candidates = [_doc("a", "a1", 1.0), _doc("b", "b1", 0.9)]

    out = diversify_context_node(_state("recall", 2, candidates), _cfg("recall"))

    assert out["rerank_debug"][0]["file_title"] == "a.md"
    assert out["context_diversify_debug"]["selected_count"] == 2
