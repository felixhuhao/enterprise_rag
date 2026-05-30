import json

import pytest

from app.api.admin_eval import (
    GoldenCaseUpdate,
    _eval_result_preview,
    _load_golden_cases,
    _normalize_golden_case_update,
    _summarize_golden_case,
)


def test_load_golden_cases_reads_jsonl(tmp_path):
    path = tmp_path / "golden.jsonl"
    path.write_text(
        json.dumps({"id": "g1", "question": "q1"}, ensure_ascii=False) + "\n"
        + json.dumps({"id": "g2", "question": "q2"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    cases = _load_golden_cases(path)

    assert [case["id"] for case in cases] == ["g1", "g2"]


def test_summarize_golden_case_exposes_config_and_counts():
    summary = _summarize_golden_case({
        "id": "g1",
        "question": "报销需要什么材料？",
        "source_config": {"retrieval_flavor": "recall", "strict_evidence": "true"},
        "eval_type": "rule",
        "expected_points": ["审批单", "发票"],
        "expected_documents": ["费用报销制度.md"],
        "min_expected_citations": 1,
    })

    assert summary["preferred_flavor"] == "recall"
    assert summary["strict_evidence"] is True
    assert summary["expected_points_count"] == 2
    assert summary["expected_points"] == ["审批单", "发票"]
    assert summary["expected_answer"] == ""
    assert summary["expected_documents"] == ["费用报销制度.md"]
    assert summary["min_expected_citations"] == 1


def test_eval_result_preview_statuses():
    assert _eval_result_preview({"id": "a", "final_score": 0.9})["status"] == "passed"
    assert _eval_result_preview({"id": "b", "final_score": 0.6})["status"] == "warning"
    assert _eval_result_preview({"id": "c", "final_score": 0.2})["status"] == "failed"
    assert _eval_result_preview({"id": "d", "final_score": None})["label"] == "待评测"
    assert _eval_result_preview({"id": "e", "error": "boom"})["status"] == "failed"


def test_normalize_golden_case_update_preserves_basic_fields():
    payload = _normalize_golden_case_update(GoldenCaseUpdate(
        question="  星辰科技住宿标准是多少？ ",
        preferred_flavor="exact",
        strict_evidence=True,
        eval_type="llm_judge",
        expected_answer="  经理以下 500，经理及以上 800。 ",
        expected_points=["  经理以下 500 元/晚 ", "", "经理及以上 800 元/晚"],
        expected_documents=["  02_费用报销制度 ", ""],
        min_expected_citations=0,
    ))

    assert payload["question"] == "星辰科技住宿标准是多少？"
    assert payload["preferred_flavor"] == "exact"
    assert payload["strict_evidence"] is True
    assert payload["expected_answer"] == "经理以下 500，经理及以上 800。"
    assert payload["expected_points"] == ["经理以下 500 元/晚", "经理及以上 800 元/晚"]
    assert payload["expected_documents"] == ["02_费用报销制度"]
    assert payload["min_expected_citations"] == 1


def test_normalize_golden_case_update_rejects_invalid_llm_case():
    with pytest.raises(ValueError, match="验收点"):
        _normalize_golden_case_update(GoldenCaseUpdate(
            question="q",
            eval_type="llm_judge",
            expected_points=[],
        ))
