from app.services.query_observability import json_dumps
from scripts import replay_intent_classifier as replay


def _row(settings: dict) -> dict:
    return {
        "id": 42,
        "query": "谁负责供应商付款审批？",
        "created_at": "2026-06-12T10:00:00",
        "settings_json": json_dumps(settings),
    }


def _settings(*, enable_multi_hop: bool = True, effective_multi_hop: bool = False) -> dict:
    return {
        "entity_mode": "none",
        "selected_entities": ["星辰科技"],
        "use_multi_hop": effective_multi_hop,
        "routing_trace": {
            "intent": {
                "entity_scope": "none",
                "needs_synthesis": False,
                "needs_discovery": False,
                "needs_multi_hop": False,
                "confidence": "low",
                "source": "deterministic",
                "fallback_used": False,
                "reasons": ["entity_scope:none"],
            },
            "policy": {
                "retrieval_breadth": "balanced",
                "strict_evidence": False,
            },
            "infra": {
                "enable_hyde": True,
                "enable_query_expansion": True,
                "enable_multi_hop": enable_multi_hop,
            },
            "routing_decision": {
                "use_hyde": True,
                "use_query_expansion": False,
                "use_multi_hop": False,
                "use_entity_fallback": False,
                "budget_reason": "balanced_current_defaults",
                "prompt_variant": "default",
                "answer_shape": "prose",
                "steps": [],
                "reasons": ["entity_scope:none"],
            },
        },
    }


def test_replay_case_from_row_reads_root_settings_json():
    case, reason = replay.replay_case_from_row(_row(_settings()))

    assert reason is None
    assert case is not None
    assert case.entity_mode == "none"
    assert case.selected_entities == ["星辰科技"]
    assert case.deterministic.confidence == "low"
    assert case.breadth == "balanced"


def test_replay_query_config_uses_logged_raw_infra_not_effective_plan_output():
    case, _reason = replay.replay_case_from_row(
        _row(_settings(enable_multi_hop=True, effective_multi_hop=False))
    )

    cfg = replay.replay_query_config(case)

    assert cfg.use_multi_hop is True


def test_replay_case_records_activatable_divergence_from_llm_discovery(monkeypatch):
    case, _reason = replay.replay_case_from_row(
        _row(_settings(enable_multi_hop=True, effective_multi_hop=False))
    )
    monkeypatch.setattr(
        replay,
        "classify_intent_llm",
        lambda query, deterministic: replay.LlmMarkers(
            needs_synthesis=False,
            needs_discovery=True,
            confidence="high",
            reasons=["responsibility discovery"],
        ),
    )

    result = replay.replay_case(case)

    assert result["merged"]["needs_multi_hop"] is True
    assert result["merged_decision"]["use_multi_hop"] is True
    assert result["diverged"] is True
    assert result["activatable"] is True


def test_replay_case_skips_missing_routing_trace():
    case, reason = replay.replay_case_from_row(_row({}))

    assert case is None
    assert reason == "no_routing_trace"
