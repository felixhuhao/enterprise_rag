from scripts import eval_golden_set
from scripts.eval_golden_set import (
    _case_query_config,
    _parse_judge_response,
    build_summary,
    load_golden_set,
    query_rag,
    run_eval,
    score_citation,
    score_rule,
)
from app.api.admin_eval import RunRequest, _failed_case_count, _filter_cases_for_run, _summarize_golden_case


def test_case_query_config_uses_preferred_flavor_and_strict():
    item = {"preferred_flavor": "recall", "strict_evidence": True}

    assert _case_query_config(item) == {
        "retrieval_flavor": "recall",
        "strict_evidence": True,
    }


def test_case_query_config_falls_back_to_source_config():
    item = {"source_config": {"retrieval_flavor": "discovery", "strict_evidence": True}}

    assert _case_query_config(item) == {
        "retrieval_flavor": "discovery",
        "strict_evidence": True,
    }


def test_case_query_config_normalizes_invalid_flavor():
    item = {"preferred_flavor": "wide", "strict_evidence": "false"}

    assert _case_query_config(item) == {
        "retrieval_flavor": "balanced",
        "strict_evidence": False,
    }


def test_summary_groups_by_actual_flavor_when_available():
    summary = build_summary([
        {
            "id": "case-1",
            "final_score": 1.0,
            "eval_type": "rule",
            "preferred_flavor": "balanced",
            "actual_retrieval_flavor": "recall",
            "strict_evidence": False,
        }
    ])

    assert "recall" in summary["per_flavor"]
    assert "balanced" not in summary["per_flavor"]


def test_query_rag_marks_request_as_eval(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_content(self, chunk_size=None, decode_unicode=False):
            yield 'data: {"type": "message_end"}\n\n'

    def fake_post(url, headers, json, stream, timeout):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(eval_golden_set.requests, "post", fake_post)

    query_rag("http://test/api", "q", "token", config={"retrieval_flavor": "balanced"})

    assert captured["json"]["is_eval"] is True


def test_load_golden_set_skips_disabled_cases(tmp_path):
    path = tmp_path / "golden.jsonl"
    path.write_text(
        '{"id": "a", "question": "active"}\n'
        '{"id": "b", "question": "disabled", "status": "disabled"}\n',
        encoding="utf-8",
    )

    items = load_golden_set(str(path))

    assert [item["id"] for item in items] == ["a"]


def test_summarize_golden_case_exposes_enabled_state():
    assert _summarize_golden_case({"id": "a", "question": "q"})["enabled"] is True
    disabled = _summarize_golden_case({"id": "b", "question": "q", "status": "disabled"})
    assert disabled["status"] == "disabled"
    assert disabled["enabled"] is False


def test_score_citation_clamps_zero_min_citations():
    result = score_citation(
        citations=[{"file_title": "doc.md"}],
        expected_documents=["doc.md"],
        min_expected_citations=0,
    )

    assert result["citation_score"] == 1.0


def test_score_rule_matches_chinese_number_variants():
    result = score_rule(
        answer="连续两个季度综合评分低于60分会被列入黑名单，三年内不得重新申请准入。",
        citations=[{
            "file_title": "08_供应商管理制度.md",
            "section_title": "星辰科技供应商管理制度 > 4. 黑名单制度",
        }],
        item={
            "numeric_expectations": [
                {"value": 2, "unit": "个季度", "tolerance": 0},
                {"value": 3, "unit": "年", "tolerance": 0},
            ],
            "must_have": ["2个季度", "60分", "3年"],
            "nice_to_have": ["黑名单"],
            "expected_documents": ["08_供应商管理制度"],
            "expected_sections": ["黑名单制度"],
            "min_expected_citations": 1,
        },
    )

    assert result["numeric_score"] == 1.0
    assert result["must_miss"] == []
    assert result["final_score"] >= 0.8


def test_score_rule_matches_wan_yuan_amount_variants():
    item = {
        "numeric_expectations": [{"value": 3, "unit": "万元", "tolerance": 0}],
        "must_have": ["CEO", "3万"],
        "nice_to_have": ["外部培训"],
        "expected_documents": ["12_年度培训计划"],
        "expected_sections": ["外部培训管理"],
        "min_expected_citations": 1,
    }

    result = score_rule(
        answer="外部培训单次费用超过30,000元，需要CEO审批。",
        citations=[{
            "file_title": "12_年度培训计划_2026.md",
            "section_title": "星辰科技年度培训计划 > 五、外部培训管理",
        }],
        item=item,
    )

    assert result["numeric_score"] == 1.0
    assert result["numeric_misses"] == []


def test_score_rule_matches_yuan_expected_with_wan_answer():
    result = score_rule(
        answer="项目预算超过200万需要CEO审批。",
        citations=[{"file_title": "09_项目管理制度.md"}],
        item={
            "numeric_expectations": [{"value": 2000000, "unit": "元", "tolerance": 0}],
            "must_have": ["CEO"],
            "nice_to_have": [],
            "expected_documents": ["09_项目管理制度"],
            "min_expected_citations": 1,
        },
    )

    assert result["numeric_score"] == 1.0


def test_parse_judge_response_extracts_json_from_prose_and_fence():
    parsed = _parse_judge_response(
        "结果如下：\n```json\n"
        '{"score": 0.82, "verdict": "pass", "missing_points": [], '
        '"unsupported_claims": [], "reason": "ok"}\n'
        "```"
    )

    assert parsed["score"] == 0.82
    assert parsed["verdict"] == "pass"


def test_parse_judge_response_falls_back_to_score_when_json_is_malformed():
    parsed = _parse_judge_response(
        '{"score": 0.66, "verdict": "warn", "reason": "missing closing quote}'
    )

    assert parsed["score"] == 0.66
    assert parsed["verdict"] == "warn"
    assert "parse_warning" in parsed


def test_run_eval_keeps_going_after_case_exception(monkeypatch):
    calls = {"count": 0}

    def fake_query_rag(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return {
            "answer": "expected",
            "citations": [],
            "trace": {},
            "retrieval_step": {},
            "rerank_results": [],
            "search_mode": "",
            "retrieval_flavor": "balanced",
            "strict_evidence": False,
            "error": None,
        }

    monkeypatch.setattr(eval_golden_set, "query_rag", fake_query_rag)

    results = run_eval(
        [
            {"id": "bad", "question": "bad", "eval_type": "rule", "expected_keywords": ["x"]},
            {"id": "ok", "question": "ok", "eval_type": "rule", "expected_keywords": ["expected"]},
        ],
        "http://test/api",
        "token",
        delay=0,
    )

    assert [row["id"] for row in results] == ["bad", "ok"]
    assert results[0]["final_score"] == 0.0
    assert "boom" in results[0]["error"]
    assert results[1]["final_score"] > 0


def test_run_eval_marks_case_timeout(monkeypatch):
    def slow_case(*_args, **_kwargs):
        import time

        time.sleep(0.05)
        return {"id": "slow", "final_score": 1.0}

    monkeypatch.setattr(eval_golden_set, "run_eval_case", slow_case)

    results = run_eval(
        [{"id": "slow", "question": "slow", "eval_type": "rule"}],
        "http://test/api",
        "token",
        delay=0,
        case_timeout_sec=0.001,
    )

    assert results[0]["id"] == "slow"
    assert results[0]["final_score"] == 0.0
    assert "timed out" in results[0]["error"]


def test_llm_judge_scores_before_case_finished(monkeypatch):
    events = []

    def fake_query_rag(*_args, **_kwargs):
        return {
            "answer": "covered answer",
            "citations": [],
            "trace": {},
            "retrieval_step": {},
            "rerank_results": [],
            "search_mode": "",
            "retrieval_flavor": "balanced",
            "strict_evidence": False,
            "error": None,
        }

    def fake_judge(**_kwargs):
        return {"score": 0.8, "verdict": "pass", "reason": "ok"}

    monkeypatch.setattr(eval_golden_set, "query_rag", fake_query_rag)
    monkeypatch.setattr(eval_golden_set, "_call_llm_judge", fake_judge)

    results = run_eval(
        [{
            "id": "judge",
            "question": "judge",
            "eval_type": "llm_judge",
            "expected_points": ["covered"],
        }],
        "http://test/api",
        "token",
        delay=0,
        judge_config={"chat_model": "model", "api_key": "key", "base_url": "url"},
        progress_callback=events.append,
    )

    finished = [event for event in events if event["type"] == "case_finished"]
    assert results[0]["judge_score"] == 0.8
    assert results[0]["final_score"] == 0.85
    assert finished[0]["row"]["final_score"] == 0.85


def test_llm_judge_error_falls_back_to_citation_score(monkeypatch):
    def fake_query_rag(*_args, **_kwargs):
        return {
            "answer": "covered answer [C1]",
            "citations": [{"id": "C1", "file_title": "doc.md"}],
            "trace": {},
            "retrieval_step": {},
            "rerank_results": [],
            "search_mode": "",
            "retrieval_flavor": "balanced",
            "strict_evidence": False,
            "error": None,
        }

    def fake_judge(**_kwargs):
        return {"error": "empty judge response"}

    monkeypatch.setattr(eval_golden_set, "query_rag", fake_query_rag)
    monkeypatch.setattr(eval_golden_set, "_call_llm_judge", fake_judge)

    results = run_eval(
        [{
            "id": "judge-empty",
            "question": "judge-empty",
            "eval_type": "llm_judge",
            "expected_points": ["covered"],
            "expected_documents": ["doc.md"],
            "min_expected_citations": 1,
        }],
        "http://test/api",
        "token",
        delay=0,
        judge_config={"chat_model": "model", "api_key": "key", "base_url": "url"},
    )

    assert results[0].get("error") is None
    assert results[0]["judge_error"] == "judge error: empty judge response"
    assert results[0]["final_score"] == 1.0
    assert results[0]["verdict"] == "pass"


def test_filter_cases_for_run_supports_ids_flavor_and_limit():
    cases = [
        {"id": "a", "preferred_flavor": "balanced"},
        {"id": "b", "preferred_flavor": "recall"},
        {"id": "c", "preferred_flavor": "recall"},
    ]

    by_ids = _filter_cases_for_run(cases, RunRequest(case_ids=["b", "missing"]))
    by_flavor = _filter_cases_for_run(cases, RunRequest(flavor="recall", limit=1))

    assert [case["id"] for case in by_ids] == ["b"]
    assert [case["id"] for case in by_flavor] == ["b"]


def test_failed_case_count_uses_preview_status():
    assert _failed_case_count([
        {"id": "ok", "final_score": 0.9},
        {"id": "warn", "final_score": 0.7},
        {"id": "bad", "final_score": 0.4},
        {"id": "error", "error": "boom", "final_score": 0.0},
    ]) == 2
