"""Unit tests for groundedness: parsing, validation, scoring, error handling."""

import pytest
from app.rag.query.groundedness import (
    GROUNDEDNESS_PROMPT,
    _parse_groundedness,
    _validate_claims,
    _compute_score,
    VERDICT_WEIGHTS,
)


class TestParseGroundedness:
    def test_prompt_uses_compact_contract(self):
        assert len(GROUNDEDNESS_PROMPT) < 900
        assert "no_answer 特殊判定规则" not in GROUNDEDNESS_PROMPT
        assert "factual 关键规则" not in GROUNDEDNESS_PROMPT
        assert '"claim_type"' in GROUNDEDNESS_PROMPT
        assert '"contradicted"' in GROUNDEDNESS_PROMPT
        assert "只输出严格 JSON" in GROUNDEDNESS_PROMPT

    def test_direct_json(self):
        parsed = _parse_groundedness('{"claims":[{"claim":"x","verdict":"supported"}]}')
        assert parsed == {"claims": [{"claim": "x", "verdict": "supported"}]}

    def test_json_fence_block(self):
        raw = '```json\n{"claims":[{"claim":"毛利率为52%","verdict":"supported"}]}\n```'
        parsed = _parse_groundedness(raw)
        assert parsed == {"claims": [{"claim": "毛利率为52%", "verdict": "supported"}]}

    def test_plain_fence_block(self):
        raw = '```\n{"claims":[{"claim":"x","verdict":"unsupported"}]}\n```'
        parsed = _parse_groundedness(raw)
        assert parsed == {"claims": [{"claim": "x", "verdict": "unsupported"}]}

    def test_invalid_json_returns_none(self):
        assert _parse_groundedness("not json at all") is None

    def test_extra_text_before_json(self):
        raw = 'Some explanation text\n{"claims":[{"claim":"x","verdict":"supported"}]}'
        parsed = _parse_groundedness(raw)
        assert parsed == {"claims": [{"claim": "x", "verdict": "supported"}]}

    def test_empty_string_returns_none(self):
        assert _parse_groundedness("") is None


class TestValidateClaims:
    def test_passes_valid_claims(self):
        claims = [
            {"claim": "毛利率为52%", "verdict": "supported", "evidence": "证据", "citation_ids": ["C1"]},
        ]
        validated = _validate_claims(claims, {"C1": {}})
        assert len(validated) == 1
        assert validated[0]["verdict"] == "supported"

    def test_filters_illegal_verdict(self):
        claims = [{"claim": "x", "verdict": "made_up"}]
        validated = _validate_claims(claims, {})
        assert validated[0]["verdict"] == "unsupported"

    def test_filters_nonexistent_citation_ids(self):
        claims = [{"claim": "x", "verdict": "supported", "citation_ids": ["C1", "C99"]}]
        validated = _validate_claims(claims, {"C1": {}})
        assert validated[0]["citation_ids"] == ["C1"]

    def test_filters_all_citation_ids_when_context_map_empty(self):
        claims = [{"claim": "x", "verdict": "supported", "citation_ids": ["C1", "C2"]}]
        validated = _validate_claims(claims, {})
        assert validated[0]["citation_ids"] == []

    def test_drops_claim_without_text(self):
        claims = [{"claim": "", "verdict": "supported"}, {"claim": "valid", "verdict": "supported"}]
        validated = _validate_claims(claims, {})
        assert len(validated) == 1
        assert validated[0]["claim"] == "valid"

    def test_drops_non_dict_claim(self):
        claims = ["not a dict", {"claim": "valid", "verdict": "supported"}]
        validated = _validate_claims(claims, {})
        assert len(validated) == 1

    def test_null_evidence_set_to_none(self):
        claims = [{"claim": "x", "verdict": "supported", "evidence": ""}]
        validated = _validate_claims(claims, {})
        assert validated[0]["evidence"] is None

    def test_no_answer_supported_forces_citation_ids_empty(self):
        claims = [{"claim": "未找到预算信息", "claim_type": "no_answer",
                   "verdict": "supported", "citation_ids": ["C1", "C2"]}]
        validated = _validate_claims(claims, {"C1": {}, "C2": {}})
        assert validated[0]["citation_ids"] == []

    def test_no_answer_supported_always_overrides_evidence(self):
        claims = [{"claim": "未找到预算信息", "claim_type": "no_answer",
                   "verdict": "supported",
                   "evidence": "无关的制度说明段落原文"}]
        validated = _validate_claims(claims, {})
        assert validated[0]["evidence"] == "上下文未包含相关信息"
        assert validated[0]["citation_ids"] == []

    def test_no_answer_contradicted_filters_illegal_cids(self):
        claims = [{"claim": "文档没有毛利率", "claim_type": "no_answer",
                   "verdict": "contradicted", "citation_ids": ["C3", "C99"]}]
        validated = _validate_claims(claims, {"C3": {}})
        assert validated[0]["citation_ids"] == ["C3"]

    def test_invalid_claim_type_falls_back_to_factual(self):
        claims = [{"claim": "x", "claim_type": "invalid", "verdict": "supported",
                   "citation_ids": ["C1"]}]
        validated = _validate_claims(claims, {"C1": {}})
        assert validated[0]["claim_type"] == "factual"
        assert validated[0]["citation_ids"] == ["C1"]  # factual keeps valid cids

    def test_claim_type_preserved_in_output(self):
        claims = [{"claim": "x", "claim_type": "no_answer", "verdict": "supported"}]
        validated = _validate_claims(claims, {})
        assert validated[0]["claim_type"] == "no_answer"


class TestComputeScore:
    def test_all_supported(self):
        claims = [
            {"verdict": "supported"}, {"verdict": "supported"}, {"verdict": "supported"},
        ]
        assert _compute_score(claims) == 1.0

    def test_mixed_verdicts(self):
        claims = [
            {"verdict": "supported"},
            {"verdict": "partially_supported"},
            {"verdict": "unsupported"},
            {"verdict": "contradicted"},
        ]
        # 1.0 + 0.5 + 0 + 0 = 1.5 / 4 = 0.375
        assert _compute_score(claims) == 0.375

    def test_partially_supported_weight(self):
        claims = [{"verdict": "partially_supported"}, {"verdict": "partially_supported"}]
        assert _compute_score(claims) == 0.5

    def test_empty_claims(self):
        assert _compute_score([]) is None

    def test_all_unsupported(self):
        claims = [{"verdict": "unsupported"}, {"verdict": "unsupported"}]
        assert _compute_score(claims) == 0.0

    def test_verdict_weights_consistency(self):
        assert VERDICT_WEIGHTS["supported"] == 1.0
        assert VERDICT_WEIGHTS["partially_supported"] == 0.5
        assert VERDICT_WEIGHTS["unsupported"] == 0.0
        assert VERDICT_WEIGHTS["contradicted"] == 0.0


class TestGroundednessNode:
    def test_skipped_when_disabled(self):
        from app.rag.query.groundedness import groundedness_check_node
        from app.rag.query.config import QueryConfig

        cfg = QueryConfig(use_groundedness=False)
        result = groundedness_check_node(
            {"answer": "test", "context_text": "ctx"},
            {"configurable": {"query_config": cfg}},
        )
        gr = result["groundedness"]
        assert gr["enabled"] is False
        assert gr["status"] == "skipped"
        assert gr["groundedness_score"] is None
        assert gr["claims"] == []

    def test_unavailable_on_empty_answer(self):
        from app.rag.query.groundedness import groundedness_check_node
        from app.rag.query.config import QueryConfig

        cfg = QueryConfig(use_groundedness=True)
        result = groundedness_check_node(
            {"answer": "", "context_text": "ctx"},
            {"configurable": {"query_config": cfg}},
        )
        gr = result["groundedness"]
        assert gr["status"] == "unavailable"

    def test_parse_array_json_returns_unavailable(self):
        """Parsed json is a valid list, not a dict → node returns unavailable."""
        from app.rag.query.groundedness import groundedness_check_node
        from app.rag.query.config import QueryConfig
        from unittest.mock import patch

        cfg = QueryConfig(use_groundedness=True)
        with patch("app.rag.query.groundedness.ChatOpenAI") as mock_llm:
            mock_llm.return_value.invoke.return_value.content = "[]"
            result = groundedness_check_node(
                {"answer": "test", "context_text": "ctx"},
                {"configurable": {"query_config": cfg}},
            )
        gr = result["groundedness"]
        assert gr["status"] == "unavailable"
        assert gr["groundedness_score"] is None

    def test_unavailable_on_llm_failure(self):
        from app.rag.query.groundedness import groundedness_check_node
        from app.rag.query.config import QueryConfig
        from unittest.mock import patch

        cfg = QueryConfig(use_groundedness=True)
        with patch("app.rag.query.groundedness.ChatOpenAI") as mock_llm:
            mock_llm.return_value.invoke.side_effect = RuntimeError("timeout")
            result = groundedness_check_node(
                {"answer": "test", "context_text": "ctx"},
                {"configurable": {"query_config": cfg}},
            )
        gr = result["groundedness"]
        assert gr["status"] == "unavailable"
        assert gr["groundedness_score"] is None
