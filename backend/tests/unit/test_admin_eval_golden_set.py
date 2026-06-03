import asyncio
import json
import shutil
from unittest.mock import AsyncMock, patch

import pytest

from app.api import admin_eval
from app.api.admin_eval import (
    GoldenCaseUpdate,
    RunRequest,
    _eval_result_detail_row,
    _eval_result_preview,
    _filter_cases_for_run,
    _load_eval_result_row,
    _load_golden_cases,
    _normalize_golden_case_update,
    _normalize_eval_mode,
    _summarize_golden_case,
    _update_eval_progress,
)
from app.api.golden_set_utils import write_jsonl_with_backup
from app.core.auth import CurrentUser


def run(coro):
    return asyncio.run(coro)


def test_load_golden_cases_reads_jsonl(tmp_path):
    path = tmp_path / "golden.jsonl"
    path.write_text(
        json.dumps({"id": "g1", "question": "q1"}, ensure_ascii=False) + "\n"
        + json.dumps({"id": "g2", "question": "q2"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    cases = _load_golden_cases(path)

    assert [case["id"] for case in cases] == ["g1", "g2"]


def test_write_jsonl_backup_does_not_copy_metadata(tmp_path, monkeypatch):
    path = tmp_path / "golden.jsonl"
    old_text = json.dumps({"id": "old"}, ensure_ascii=False) + "\n"
    path.write_text(old_text, encoding="utf-8")

    def fail_copystat(*args, **kwargs):
        raise PermissionError("metadata copy denied")

    monkeypatch.setattr(shutil, "copystat", fail_copystat)

    write_jsonl_with_backup(path, [{"id": "new"}])

    backups = list(tmp_path.glob("golden.jsonl.bak_*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == old_text
    assert json.loads(path.read_text(encoding="utf-8")) == {"id": "new"}


def test_summarize_golden_case_exposes_config_and_counts():
    summary = _summarize_golden_case({
        "id": "g1",
        "question": "报销需要什么材料？",
        "source_config": {"retrieval_flavor": "recall", "strict_evidence": "true"},
        "eval_type": "rule",
        "expected_points": ["审批单", "发票"],
        "expected_documents": ["费用报销制度.md"],
        "expected_docs": ["费用报销制度.md"],
        "expected_chunk_keys": ["ck_1"],
        "quick": True,
        "slices": ["quick", "exact"],
        "expected_behavior": "answer",
        "min_expected_citations": 1,
    })

    assert summary["preferred_flavor"] == "recall"
    assert summary["strict_evidence"] is True
    assert summary["expected_points_count"] == 2
    assert summary["expected_points"] == ["审批单", "发票"]
    assert summary["expected_answer"] == ""
    assert summary["expected_documents"] == ["费用报销制度.md"]
    assert summary["expected_docs"] == ["费用报销制度.md"]
    assert summary["expected_chunk_keys"] == ["ck_1"]
    assert summary["quick"] is True
    assert summary["slices"] == ["quick", "exact"]
    assert summary["expected_behavior"] == "answer"
    assert summary["min_expected_citations"] == 1


def test_filter_cases_for_run_supports_quick_mode():
    cases = [
        {"id": "a", "quick": True, "preferred_flavor": "balanced"},
        {"id": "b", "quick": False, "preferred_flavor": "balanced"},
        {"id": "c", "quick": "true", "preferred_flavor": "recall"},
        {"id": "d", "quick": True, "preferred_flavor": "balanced", "status": "disabled"},
    ]

    assert [case["id"] for case in _filter_cases_for_run(cases, RunRequest(mode="quick"))] == ["a", "c"]
    assert [case["id"] for case in _filter_cases_for_run(cases, RunRequest(mode="quick", flavor="recall"))] == ["c"]


def test_filter_cases_for_run_excludes_disabled_explicit_case_ids():
    cases = [
        {"id": "a", "quick": True, "preferred_flavor": "balanced"},
        {"id": "b", "quick": True, "preferred_flavor": "balanced", "status": "disabled"},
    ]

    selected = _filter_cases_for_run(cases, RunRequest(mode="quick", case_ids=["a", "b"]))

    assert [case["id"] for case in selected] == ["a"]


def test_normalize_eval_mode_rejects_unknown_mode():
    assert _normalize_eval_mode("") == "full"
    assert _normalize_eval_mode("answer_lite") == "answer_lite"
    with pytest.raises(ValueError, match="评测模式无效"):
        _normalize_eval_mode("wide")


def test_eval_result_preview_statuses():
    assert _eval_result_preview({"id": "a", "final_score": 0.9})["status"] == "passed"
    assert _eval_result_preview({"id": "b", "final_score": 0.6})["status"] == "warning"
    assert _eval_result_preview({"id": "c", "final_score": 0.2})["status"] == "failed"
    pending = _eval_result_preview({"id": "d", "final_score": None})
    assert pending["status"] == "warning"
    assert pending["label"] == "待评测"
    assert _eval_result_preview({"id": "e", "error": "boom"})["status"] == "failed"
    preview = _eval_result_preview({
        "id": "f",
        "final_score": 0.0,
        "eval_mode": "answer_lite",
        "eval_type": "llm_judge",
        "preferred_flavor": "recall",
        "actual_retrieval_flavor": "balanced",
        "strict_evidence": True,
        "failure_category": "retrieval_miss",
        "failure_categories": ["retrieval_miss", "answer_incomplete"],
    })
    assert preview["failure_category"] == "retrieval_miss"
    assert preview["failure_categories"] == ["retrieval_miss", "answer_incomplete"]
    assert preview["eval_mode"] == "answer_lite"
    assert preview["eval_type"] == "llm_judge"
    assert preview["preferred_flavor"] == "recall"
    assert preview["actual_retrieval_flavor"] == "balanced"
    assert preview["strict_evidence"] is True


def test_eval_result_detail_row_fills_safe_defaults():
    detail = _eval_result_detail_row({
        "id": "case_1",
        "question": "q",
        "expected_documents": ["policy.md"],
    })

    assert detail["expected_docs"] == ["policy.md"]
    assert detail["expected_documents"] == ["policy.md"]
    assert detail["actual_answer"] == ""
    assert detail["actual_citations"] == []
    assert detail["rerank_results"] == []
    assert detail["retrieval_step"] == {}
    assert detail["trace"] == {}
    assert detail["failure_categories"] == []
    assert detail["judge"] == {}
    assert detail["groundedness"] == {}


def test_load_eval_result_row_reads_matching_case(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text(
        json.dumps({"id": "case_1", "question": "q1"}, ensure_ascii=False) + "\n"
        + json.dumps({
            "id": "case_2",
            "question": "q2",
            "actual_answer": "answer",
            "expected_docs": ["policy.md"],
            "failure_categories": ["citation_missing"],
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    row = _load_eval_result_row(path, "case_2")

    assert row["id"] == "case_2"
    assert row["actual_answer"] == "answer"
    assert row["expected_docs"] == ["policy.md"]
    assert row["expected_documents"] == ["policy.md"]
    assert row["failure_categories"] == ["citation_missing"]


def test_load_eval_result_row_reports_missing_case(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text(json.dumps({"id": "case_1"}, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(KeyError):
        _load_eval_result_row(path, "missing")


def test_load_eval_result_row_reports_invalid_json(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text('{"id": "case_1"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ValueError, match="有效 JSON"):
        _load_eval_result_row(path, "case_2")


def test_find_latest_eval_result_row_scans_recent_files(tmp_path, monkeypatch):
    older = tmp_path / "eval_20260101_000000_results.jsonl"
    newer = tmp_path / "eval_20260101_000001_results.jsonl"
    older.write_text(json.dumps({"id": "case_1", "final_score": 0.5}, ensure_ascii=False) + "\n", encoding="utf-8")
    newer.write_text(json.dumps({"id": "case_2", "final_score": 1.0}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(admin_eval, "RESULT_DIR", tmp_path)

    path, row = admin_eval._find_latest_eval_result_row("case_1")

    assert path == older
    assert row["id"] == "case_1"


def test_load_eval_result_row_for_case_falls_back_after_state_reset(tmp_path, monkeypatch):
    result_path = tmp_path / "eval_20260101_000000_results.jsonl"
    result_path.write_text(json.dumps({"id": "case_1", "question": "q"}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(admin_eval, "RESULT_DIR", tmp_path)
    with admin_eval._lock:
        old_path = admin_eval._state.get("result_path", "")
        admin_eval._state["result_path"] = ""

    try:
        path, row = admin_eval._load_eval_result_row_for_case("case_1")
    finally:
        with admin_eval._lock:
            admin_eval._state["result_path"] = old_path

    assert path == result_path
    assert row["id"] == "case_1"


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


def test_update_eval_progress_updates_job_progress():
    update_progress = AsyncMock()
    with admin_eval._lock:
        old_state = dict(admin_eval._state)
        admin_eval._state.update({
            "total": 0,
            "current": 0,
            "current_id": "",
            "current_question": "",
            "results_preview": [],
        })

    try:
        with patch("app.api.admin_eval.job_service.update_job_progress", update_progress):
            _update_eval_progress({
                "type": "case_finished",
                "index": 1,
                "total": 3,
                "row": {
                    "id": "case_1",
                    "question": "q",
                    "final_score": 1.0,
                },
            }, job_id="job-1")
    finally:
        with admin_eval._lock:
            admin_eval._state.clear()
            admin_eval._state.update(old_state)

    update_progress.assert_awaited_once_with(
        "job-1",
        progress_current=1,
        progress_total=3,
        message="finished case_1",
    )


def test_run_eval_creates_job_and_returns_job_id():
    created_threads = []

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            created_threads.append(self)

    create_job = AsyncMock(return_value={"job_id": "job-eval"})
    req = RunRequest(mode="retrieval_only")
    user = CurrentUser(user_id="admin", username="Admin", role="admin")

    with admin_eval._lock:
        old_state = dict(admin_eval._state)
        admin_eval._state.update({"status": "idle", "job_id": ""})

    try:
        with patch("app.api.admin_eval.job_service.create_job", create_job), \
             patch("app.api.admin_eval.threading.Thread", FakeThread):
            result = run(admin_eval.run_eval(req, current_user=user, authorization="Bearer token-123"))
    finally:
        with admin_eval._lock:
            admin_eval._state.clear()
            admin_eval._state.update(old_state)

    assert result == {"ok": True, "status": "running", "job_id": "job-eval"}
    create_job.assert_awaited_once_with(
        job_type=admin_eval.EVAL_JOB_TYPE,
        resource_type=admin_eval.EVAL_JOB_RESOURCE_TYPE,
        resource_id=admin_eval.EVAL_JOB_RESOURCE_ID,
        created_by="admin",
        message="queued mode=retrieval_only",
    )
    assert len(created_threads) == 1
    thread = created_threads[0]
    assert thread.target == admin_eval._runner
    assert thread.args == ("token-123", req, "job-eval")
    assert thread.daemon is True
