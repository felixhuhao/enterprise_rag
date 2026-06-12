"""Pure scoring units for the 2C-1 routing golden set."""

from __future__ import annotations

from typing import Any, Mapping

from app.rag.query.config import QueryConfig
from app.rag.query.control.budget import resolve_budget_profile
from app.rag.query.control.inferred import InferredSignals
from app.rag.query.control.routing import (
    RoutingDecision,
    decision_execution_dict,
    derive_routing_decision,
)


def build_expected_intent(expected: Mapping[str, Any]) -> InferredSignals:
    """Build labeled expected intent; needs_multi_hop is re-derived."""
    scope = str(expected["entity_scope"])
    needs_synthesis = bool(expected.get("needs_synthesis", False))
    needs_discovery = bool(expected.get("needs_discovery", False))
    needs_multi_hop = scope in ("broad", "none") and needs_discovery
    return InferredSignals(
        entity_scope=scope,
        needs_synthesis=needs_synthesis,
        needs_discovery=needs_discovery,
        needs_multi_hop=needs_multi_hop,
    )


def route_for_intent(intent: InferredSignals, breadth: str, cfg: QueryConfig) -> RoutingDecision:
    """Resolve budget per intent, then derive the route."""
    budget = resolve_budget_profile(breadth, intent.entity_scope, intent.needs_synthesis, cfg)
    return derive_routing_decision(intent, breadth, cfg, budget_reason=budget.reason)


def score_case(
    case_class: str,
    must_activate: bool,
    confidence: str,
    *,
    actual: RoutingDecision | Mapping[str, Any],
    expected: RoutingDecision | Mapping[str, Any],
    design1: RoutingDecision | Mapping[str, Any],
) -> dict[str, Any]:
    """Classify one case's post-gate outcome."""
    actual_x = decision_execution_dict(actual)
    expected_x = decision_execution_dict(expected)
    design1_x = decision_execution_dict(design1)

    route_correct = actual_x == expected_x
    activated = confidence == "high"
    actual_eq_design1 = actual_x == design1_x

    is_clear = case_class == "clear"
    is_ambiguous = case_class == "ambiguous"
    return {
        "case_class": case_class,
        "must_activate": must_activate,
        "route_correct": route_correct,
        "activated": activated,
        "missed_activation": is_clear and must_activate and not activated,
        "wrong_route": is_clear and activated and not route_correct,
        "ambiguous_safe_default": is_ambiguous and not activated and actual_eq_design1,
        "ambiguous_safe_pass": is_ambiguous and (route_correct or (not activated and actual_eq_design1)),
        "ambiguous_confident_wrong": is_ambiguous and activated and not route_correct,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate scored rows into 2C-1 metrics and gate verdicts."""
    clear = [r for r in rows if r["case_class"] == "clear"]
    ambiguous = [r for r in rows if r["case_class"] == "ambiguous"]

    def rate(items: list[dict[str, Any]], key: str) -> float:
        return round(sum(1 for row in items if row[key]) / len(items), 4) if items else 0.0

    clear_acc = rate(clear, "route_correct")
    det_clear_acc = rate(clear, "deterministic_route_correct")

    must_activate_clear = [r for r in clear if r.get("must_activate")]
    clear_missed = rate(must_activate_clear, "missed_activation")

    ambiguous_safe_default = sum(1 for r in ambiguous if r.get("ambiguous_safe_default"))
    ambiguous_safe_pass = rate(ambiguous, "ambiguous_safe_pass")
    clear_control_regressions = [
        r for r in clear
        if r.get("category") == "clear_control" and not r.get("route_correct")
    ]

    def marker_pr(items: list[dict[str, Any]], field: str) -> dict[str, Any]:
        tp = sum(
            1 for row in items
            if row.get("merged_markers", {}).get(field) is True
            and row.get("expected_markers", {}).get(field) is True
        )
        fp = sum(
            1 for row in items
            if row.get("merged_markers", {}).get(field) is True
            and row.get("expected_markers", {}).get(field) is not True
        )
        fn = sum(
            1 for row in items
            if row.get("merged_markers", {}).get(field) is not True
            and row.get("expected_markers", {}).get(field) is True
        )
        return {
            "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
            "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }

    def metric_block(items: list[dict[str, Any]]) -> dict[str, Any]:
        block_clear = [r for r in items if r["case_class"] == "clear"]
        block_ambiguous = [r for r in items if r["case_class"] == "ambiguous"]
        block_must_activate = [r for r in block_clear if r.get("must_activate")]
        block_clear_acc = rate(block_clear, "route_correct")
        block_det_clear_acc = rate(block_clear, "deterministic_route_correct")
        return {
            "count": len(items),
            "clear_expected_route_accuracy": block_clear_acc,
            "clear_missed_activation_rate": rate(block_must_activate, "missed_activation"),
            "clear_wrong_route_count": sum(1 for r in block_clear if r["wrong_route"]),
            "ambiguous_safe_default_rate": rate(block_ambiguous, "ambiguous_safe_default"),
            "ambiguous_safe_pass_rate": rate(block_ambiguous, "ambiguous_safe_pass"),
            "ambiguous_confident_wrong_count": sum(
                1 for r in block_ambiguous if r["ambiguous_confident_wrong"]
            ),
            "deterministic_clear_accuracy": block_det_clear_acc,
            "llm_vs_deterministic_delta": round(block_clear_acc - block_det_clear_acc, 4),
            "marker_precision_recall": {
                "needs_synthesis": marker_pr(items, "needs_synthesis"),
                "needs_discovery": marker_pr(items, "needs_discovery"),
            },
        }

    categories = sorted({row.get("category", "unknown") for row in rows})
    per_category = {
        category: metric_block([row for row in rows if row.get("category") == category])
        for category in categories
    }

    summary: dict[str, Any] = {
        "counts": {"total": len(rows), "clear": len(clear), "ambiguous": len(ambiguous)},
        "clear_expected_route_accuracy": clear_acc,
        "clear_missed_activation_rate": clear_missed,
        "clear_wrong_route_rate": rate(clear, "wrong_route"),
        "clear_wrong_route_count": sum(1 for r in clear if r["wrong_route"]),
        "ambiguous_safe_default_rate": (
            round(ambiguous_safe_default / len(ambiguous), 4) if ambiguous else 0.0
        ),
        "ambiguous_safe_pass_rate": ambiguous_safe_pass,
        "ambiguous_confident_wrong_count": sum(
            1 for r in ambiguous if r["ambiguous_confident_wrong"]
        ),
        "deterministic_clear_accuracy": det_clear_acc,
        "llm_vs_deterministic_delta": round(clear_acc - det_clear_acc, 4),
        "clear_control_route_regression_count": len(clear_control_regressions),
        "clear_control_route_regression_ids": [r.get("id") for r in clear_control_regressions],
        "marker_precision_recall": {
            "needs_synthesis": marker_pr(rows, "needs_synthesis"),
            "needs_discovery": marker_pr(rows, "needs_discovery"),
        },
        "per_category": per_category,
    }
    summary["gates"] = {
        "clear_expected_route_accuracy>=0.9": clear_acc >= 0.9,
        "ambiguous_confident_wrong_count==0": summary["ambiguous_confident_wrong_count"] == 0,
        "clear_wrong_route_count==0": summary["clear_wrong_route_count"] == 0,
        "llm_vs_deterministic_delta>=0": summary["llm_vs_deterministic_delta"] >= 0,
        "clear_control_route_regression_count==0": summary["clear_control_route_regression_count"] == 0,
    }
    return summary
