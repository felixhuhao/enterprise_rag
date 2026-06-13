from app.rag.query.config import QueryConfig
from app.rag.query.control.inferred import InferredSignals
from app.rag.query.control.route_scoring import (
    aggregate,
    build_expected_intent,
    route_for_intent,
    score_case,
)


def test_build_expected_intent_rederives_multi_hop():
    exp = build_expected_intent({
        "entity_scope": "none",
        "needs_synthesis": False,
        "needs_discovery": True,
    })
    assert exp.needs_multi_hop is True

    exp2 = build_expected_intent({
        "entity_scope": "single",
        "needs_synthesis": True,
        "needs_discovery": False,
    })
    assert exp2.needs_multi_hop is False


def test_route_for_intent_uses_per_intent_budget():
    cfg = QueryConfig()
    plain = InferredSignals("single", False, False, False)
    synth = InferredSignals("single", True, False, False)
    discovery = InferredSignals("none", False, True, True)
    multi_synth_discovery = InferredSignals("multi", True, True, False)

    assert route_for_intent(plain, "balanced", cfg).budget_reason == "balanced_current_defaults"
    assert route_for_intent(synth, "balanced", cfg).budget_reason == "balanced_synthesis"
    assert route_for_intent(discovery, "balanced", cfg).budget_reason == "balanced_discovery"
    assert route_for_intent(discovery, "balanced", cfg).prompt_variant == "broad"
    assert route_for_intent(multi_synth_discovery, "balanced", cfg).budget_reason == "balanced_synthesis"


def _exec(**over):
    base = {
        "use_hyde": False,
        "use_query_expansion": False,
        "use_multi_hop": False,
        "use_entity_fallback": False,
        "budget_reason": "balanced_current_defaults",
        "prompt_variant": "default",
        "answer_shape": "prose",
        "steps": [],
    }
    base.update(over)
    return base


def test_score_clear_correct_and_missed_and_wrong():
    expected = _exec(use_multi_hop=True)

    r = score_case(
        "clear",
        True,
        "high",
        actual=_exec(use_multi_hop=True),
        expected=expected,
        design1=_exec(),
    )
    assert r["route_correct"]
    assert not r["wrong_route"]
    assert not r["missed_activation"]

    r2 = score_case("clear", True, "medium", actual=_exec(), expected=expected, design1=_exec())
    assert r2["missed_activation"]
    assert not r2["route_correct"]
    assert not r2["wrong_route"]

    r3 = score_case(
        "clear",
        True,
        "high",
        actual=_exec(use_hyde=True),
        expected=expected,
        design1=_exec(),
    )
    assert r3["wrong_route"]
    assert not r3["route_correct"]


def test_score_ambiguous_safe_pass_vs_confident_wrong():
    expected = _exec(use_multi_hop=True)
    design1 = _exec()

    r = score_case("ambiguous", False, "low", actual=design1, expected=expected, design1=design1)
    assert r["ambiguous_safe_default"]
    assert r["ambiguous_safe_pass"]
    assert not r["ambiguous_confident_wrong"]

    r2 = score_case("ambiguous", False, "high", actual=design1, expected=expected, design1=design1)
    assert r2["ambiguous_confident_wrong"]
    assert not r2["ambiguous_safe_pass"]
    assert not r2["ambiguous_safe_default"]

    r3 = score_case("ambiguous", False, "high", actual=expected, expected=expected, design1=design1)
    assert r3["ambiguous_safe_pass"]
    assert not r3["ambiguous_confident_wrong"]
    assert not r3["ambiguous_safe_default"]


def test_aggregate_metrics_and_gates():
    rows = [
        {
            "id": "implicit_synthesis_001",
            "case_class": "clear",
            "must_activate": True,
            "route_correct": True,
            "activated": True,
            "missed_activation": False,
            "wrong_route": False,
            "ambiguous_safe_default": False,
            "ambiguous_safe_pass": False,
            "ambiguous_confident_wrong": False,
            "deterministic_route_correct": False,
            "category": "implicit_synthesis",
            "expected_markers": {"needs_synthesis": True, "needs_discovery": False},
            "merged_markers": {"needs_synthesis": True, "needs_discovery": False},
        },
        {
            "id": "discovery_no_keyword_001",
            "case_class": "clear",
            "must_activate": True,
            "route_correct": False,
            "activated": False,
            "missed_activation": True,
            "wrong_route": False,
            "ambiguous_safe_default": False,
            "ambiguous_safe_pass": False,
            "ambiguous_confident_wrong": False,
            "deterministic_route_correct": False,
            "category": "discovery_no_keyword",
            "expected_markers": {"needs_synthesis": False, "needs_discovery": True},
            "merged_markers": {"needs_synthesis": False, "needs_discovery": False},
        },
        {
            "id": "paraphrase_001",
            "case_class": "ambiguous",
            "must_activate": False,
            "route_correct": True,
            "activated": True,
            "missed_activation": False,
            "wrong_route": False,
            "ambiguous_safe_default": False,
            "ambiguous_safe_pass": True,
            "ambiguous_confident_wrong": False,
            "deterministic_route_correct": True,
            "category": "paraphrase",
            "expected_markers": {"needs_synthesis": False, "needs_discovery": True},
            "merged_markers": {"needs_synthesis": False, "needs_discovery": True},
        },
    ]

    s = aggregate(rows)

    assert s["clear_expected_route_accuracy"] == 0.5
    assert s["clear_missed_activation_rate"] == 0.5
    assert s["clear_wrong_route_count"] == 0
    assert s["ambiguous_confident_wrong_count"] == 0
    assert s["ambiguous_safe_default_rate"] == 0.0
    assert s["ambiguous_safe_pass_rate"] == 1.0
    assert s["llm_vs_deterministic_delta"] == 0.5
    assert s["marker_precision_recall"]["needs_synthesis"]["precision"] == 1.0
    assert s["marker_precision_recall"]["needs_discovery"]["recall"] == 0.5
    assert s["clear_control_route_regression_count"] == 0
    assert s["per_category"]["implicit_synthesis"]["count"] == 1
    assert s["gates"]["clear_expected_route_accuracy>=0.9"] is False
    assert s["gates"]["ambiguous_confident_wrong_count==0"] is True
    assert s["gates"]["clear_wrong_route_count==0"] is True
    assert s["gates"]["clear_control_route_regression_count==0"] is True
