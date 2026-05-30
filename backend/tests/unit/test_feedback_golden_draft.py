from app.api import query_feedback
from app.api.query_feedback import (
    GoldenDraftUpdate,
    _build_golden_draft,
    _draft_feedback_ids,
    _draft_to_golden_case,
    _find_existing_draft,
    _load_golden_drafts,
    _save_golden_drafts,
    _update_draft_fields,
)


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


def test_load_golden_drafts_skips_bad_lines(tmp_path, monkeypatch):
    path = tmp_path / "feedback_draft.jsonl"
    path.write_text(
        '{"source_feedback_id": 7, "question": "q1"}\n'
        'not-json\n'
        '{"source_feedback_id": "8", "question": "q2"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(query_feedback, "GOLDEN_DRAFT_PATH", path)

    drafts = _load_golden_drafts()

    assert [d["question"] for d in drafts] == ["q1", "q2"]
    assert _draft_feedback_ids() == {7, 8}
    assert _find_existing_draft(7)["question"] == "q1"
    assert _find_existing_draft(9) is None


def test_save_and_update_golden_draft(tmp_path, monkeypatch):
    path = tmp_path / "feedback_draft.jsonl"
    monkeypatch.setattr(query_feedback, "GOLDEN_DRAFT_PATH", path)
    monkeypatch.setattr(query_feedback, "GOLDEN_DRAFT_DIR", tmp_path)

    _save_golden_drafts([{"id": "fb_1", "question": "old", "source_feedback_id": 1}])
    draft = _load_golden_drafts()[0]
    updated = _update_draft_fields(
        draft,
        GoldenDraftUpdate(
            question="new question",
            preferred_flavor="recall",
            strict_evidence=True,
            eval_type="llm_judge",
            expected_points=[" p1 ", "", "p2"],
            expected_documents=["doc.md", ""],
            min_expected_citations=2,
        ),
    )

    assert updated["question"] == "new question"
    assert updated["preferred_flavor"] == "recall"
    assert updated["strict_evidence"] is True
    assert updated["expected_points"] == ["p1", "p2"]
    assert updated["expected_documents"] == ["doc.md"]
    assert updated["source_config"] == {
        "retrieval_flavor": "recall",
        "strict_evidence": True,
    }


def test_draft_to_golden_case_marks_active():
    case = _draft_to_golden_case({
        "id": "fb_1",
        "question": "q",
        "preferred_flavor": "exact",
        "strict_evidence": True,
        "expected_points": ["p"],
    })

    assert case["status"] == "active"
    assert case["source_config"] == {
        "retrieval_flavor": "exact",
        "strict_evidence": True,
    }
    assert "published_at" in case
