from app.api.query_feedback import _build_golden_draft


def test_golden_draft_preserves_query_config():
    draft = _build_golden_draft({
        "id": 7,
        "query": "test question",
        "answer": "bad answer",
        "rating": "down",
        "comment": "missed source",
        "citations": "[]",
        "retrieved_chunks": "[]",
        "retrieval_flavor": "recall",
        "strict_evidence": 1,
        "user_id": "u1",
    })

    assert draft["preferred_flavor"] == "recall"
    assert draft["strict_evidence"] is True
    assert draft["source_config"] == {
        "retrieval_flavor": "recall",
        "strict_evidence": True,
    }


def test_golden_draft_normalizes_invalid_flavor():
    draft = _build_golden_draft({
        "id": 8,
        "query": "test question",
        "citations": "[]",
        "retrieved_chunks": "[]",
        "retrieval_flavor": "wide",
        "strict_evidence": "false",
    })

    assert draft["preferred_flavor"] == "balanced"
    assert draft["strict_evidence"] is False
