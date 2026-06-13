from unittest.mock import patch

from app.config import settings
from app.rag.query.control import llm_classifier
from app.rag.query.control.inferred import InferredSignals, infer_signals
from app.rag.query.control.llm_classifier import classify_intent_llm, parse_llm_markers


def test_parse_llm_markers_clean_json():
    markers = parse_llm_markers(
        '{"needs_synthesis":true,"needs_discovery":false,'
        '"confidence":"high","reasons":["implicit comparison"]}'
    )

    assert markers is not None
    assert markers.needs_synthesis is True
    assert markers.needs_discovery is False
    assert markers.confidence == "high"
    assert markers.reasons == ["implicit comparison"]


def test_parse_llm_markers_fenced_json():
    markers = parse_llm_markers(
        '```json\n{"needs_synthesis":false,"needs_discovery":true,'
        '"confidence":"medium","reasons":["responsibility"]}\n```'
    )

    assert markers is not None
    assert markers.needs_discovery is True
    assert markers.confidence == "medium"


def test_parse_llm_markers_accepts_empty_reasons():
    markers = parse_llm_markers(
        '{"needs_synthesis":false,"needs_discovery":false,'
        '"confidence":"low","reasons":[]}'
    )

    assert markers is not None
    assert markers.reasons == []


def test_parse_llm_markers_filters_non_string_reasons():
    markers = parse_llm_markers(
        '{"needs_synthesis":false,"needs_discovery":true,'
        '"confidence":"high","reasons":[123,null," valid ",""]}'
    )

    assert markers is not None
    assert markers.reasons == ["valid"]


def test_parse_llm_markers_rejects_schema_violation():
    assert parse_llm_markers(
        '{"needs_synthesis":"yes","needs_discovery":false,'
        '"confidence":"high","reasons":[]}'
    ) is None
    assert parse_llm_markers(
        '{"needs_synthesis":true,"needs_discovery":false,'
        '"confidence":"certain","reasons":[]}'
    ) is None


def test_parse_llm_markers_rejects_missing_fields():
    assert parse_llm_markers(
        '{"needs_synthesis":true,"confidence":"high","reasons":[]}'
    ) is None


def test_classify_intent_llm_uses_settings_and_model_fallback(monkeypatch):
    monkeypatch.setattr(settings, "INTENT_CLASSIFIER_MODEL", "")
    monkeypatch.setattr(settings, "CHAT_MODEL", "chat-default")
    monkeypatch.setattr(settings, "INTENT_CLASSIFIER_TIMEOUT", 7)
    monkeypatch.setattr(settings, "INTENT_CLASSIFIER_MAX_TOKENS", 123)

    with patch("app.rag.query.control.llm_classifier.ChatOpenAI") as mock_llm:
        mock_llm.return_value.invoke.return_value.content = (
            '{"needs_synthesis":false,"needs_discovery":true,'
            '"confidence":"high","reasons":["implicit discovery"]}'
        )
        markers = classify_intent_llm("谁负责供应商付款审批？", infer_signals("q", "none", []))

    assert markers is not None
    assert markers.needs_discovery is True
    assert markers.confidence == "high"
    kwargs = mock_llm.call_args.kwargs
    assert kwargs["model"] == "chat-default"
    assert kwargs["timeout"] == 7
    assert kwargs["max_retries"] == 1
    assert kwargs["max_tokens"] == 123


def test_classify_intent_llm_parses_fenced_json():
    with patch("app.rag.query.control.llm_classifier.ChatOpenAI") as mock_llm:
        mock_llm.return_value.invoke.return_value.content = (
            '```json\n{"needs_synthesis":true,"needs_discovery":false,'
            '"confidence":"high","reasons":["implicit comparison"]}\n```'
        )
        markers = classify_intent_llm("A和B有什么区别？", infer_signals("q", "single", []))

    assert markers is not None
    assert markers.needs_synthesis is True
    assert markers.confidence == "high"


def test_classify_intent_llm_downgrades_high_no_marker_on_non_high_deterministic():
    with patch("app.rag.query.control.llm_classifier.ChatOpenAI") as mock_llm:
        mock_llm.return_value.invoke.return_value.content = (
            '{"needs_synthesis":false,"needs_discovery":false,'
            '"confidence":"high","reasons":["plain lookup"]}'
        )
        markers = classify_intent_llm("流程最后算到哪儿？", infer_signals("q", "none", []))

    assert markers is not None
    assert markers.confidence == "medium"
    assert "calibrated:no routing marker" in " ".join(markers.reasons)


def test_classify_intent_llm_keeps_high_when_marker_added():
    with patch("app.rag.query.control.llm_classifier.ChatOpenAI") as mock_llm:
        mock_llm.return_value.invoke.return_value.content = (
            '{"needs_synthesis":false,"needs_discovery":true,'
            '"confidence":"high","reasons":["implicit discovery"]}'
        )
        markers = classify_intent_llm("流程最后算到哪儿？", infer_signals("q", "none", []))

    assert markers is not None
    assert markers.confidence == "high"


def test_classify_intent_llm_keeps_high_no_marker_on_high_deterministic():
    with patch("app.rag.query.control.llm_classifier.ChatOpenAI") as mock_llm:
        mock_llm.return_value.invoke.return_value.content = (
            '{"needs_synthesis":false,"needs_discovery":false,'
            '"confidence":"high","reasons":["plain broad lookup"]}'
        )
        markers = classify_intent_llm("所有公司的报销标准", infer_signals("q", "broad", []))

    assert markers is not None
    assert markers.confidence == "high"


def test_classify_intent_llm_returns_none_on_garbage_response():
    with patch("app.rag.query.control.llm_classifier.ChatOpenAI") as mock_llm:
        mock_llm.return_value.invoke.return_value.content = "not json"
        markers = classify_intent_llm("q", infer_signals("q", "none", []))

    assert markers is None


def test_classify_intent_llm_returns_none_on_schema_violation():
    with patch("app.rag.query.control.llm_classifier.ChatOpenAI") as mock_llm:
        mock_llm.return_value.invoke.return_value.content = (
            '{"needs_synthesis":"yes","needs_discovery":false,'
            '"confidence":"high","reasons":[]}'
        )
        markers = classify_intent_llm("q", infer_signals("q", "none", []))

    assert markers is None


def test_classify_intent_llm_returns_none_on_exception():
    with patch("app.rag.query.control.llm_classifier.ChatOpenAI") as mock_llm:
        mock_llm.return_value.invoke.side_effect = RuntimeError("timeout")
        markers = classify_intent_llm("q", infer_signals("q", "none", []))

    assert markers is None


def _det(confidence="medium"):
    return InferredSignals("single", False, False, False, confidence=confidence)


def test_classify_intent_inline_success(monkeypatch):
    seen = {}

    def fake_invoke(q, d, t, *, max_retries):
        seen["timeout"] = t
        seen["max_retries"] = max_retries
        return (
            '{"needs_synthesis":true,"needs_discovery":false,'
            '"confidence":"high","reasons":["x"]}'
        )

    monkeypatch.setattr(
        llm_classifier,
        "_invoke_classifier",
        fake_invoke,
    )

    result = llm_classifier.classify_intent_inline("q", _det())

    assert seen == {"timeout": settings.INTENT_CLASSIFIER_INLINE_TIMEOUT, "max_retries": 0}
    assert result.fallback_reason == "none"
    assert result.markers is not None
    assert result.markers.needs_synthesis is True
    assert result.latency_ms >= 0


def test_classify_intent_inline_parse_fail(monkeypatch):
    monkeypatch.setattr(llm_classifier, "_invoke_classifier", lambda q, d, t, *, max_retries: "not json")

    result = llm_classifier.classify_intent_inline("q", _det())

    assert result.fallback_reason == "parse_fail"
    assert result.markers is None


def test_classify_intent_inline_timeout(monkeypatch):
    class APITimeoutError(Exception):
        pass

    def boom(q, d, t, *, max_retries):
        raise APITimeoutError("slow")

    monkeypatch.setattr(llm_classifier, "_invoke_classifier", boom)

    result = llm_classifier.classify_intent_inline("q", _det())

    assert result.fallback_reason == "timeout"
    assert result.markers is None


def test_classify_intent_inline_error(monkeypatch):
    def boom(q, d, t, *, max_retries):
        raise ValueError("boom")

    monkeypatch.setattr(llm_classifier, "_invoke_classifier", boom)

    result = llm_classifier.classify_intent_inline("q", _det())

    assert result.fallback_reason == "error"
    assert result.markers is None


def test_is_timeout_recognizes_provider_types():
    class APITimeoutError(Exception):
        pass

    class TimeoutException(Exception):
        pass

    assert llm_classifier._is_timeout(APITimeoutError()) is True
    assert llm_classifier._is_timeout(TimeoutException()) is True
    assert llm_classifier._is_timeout(TimeoutError()) is True
    assert llm_classifier._is_timeout(ValueError()) is False


def test_is_timeout_recognizes_wrapped_provider_timeout():
    class APITimeoutError(Exception):
        pass

    wrapped = RuntimeError("request failed")
    wrapped.__cause__ = APITimeoutError("slow")

    assert llm_classifier._is_timeout(wrapped) is True


def test_classify_intent_llm_delegates_and_swallows(monkeypatch):
    monkeypatch.setattr(
        llm_classifier,
        "_invoke_classifier",
        lambda q, d, t, *, max_retries: '{"needs_synthesis":false,"needs_discovery":true,'
        '"confidence":"high","reasons":[]}',
    )

    markers = llm_classifier.classify_intent_llm("q", _det())

    assert markers is not None and markers.needs_discovery is True

    def boom(q, d, t, *, max_retries):
        raise ValueError("x")

    monkeypatch.setattr(llm_classifier, "_invoke_classifier", boom)

    assert llm_classifier.classify_intent_llm("q", _det()) is None
