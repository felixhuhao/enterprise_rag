"""Paired-run leak check for Design 2C-3 activation."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

_DECISION_FIELDS = (
    "use_hyde",
    "use_query_expansion",
    "use_multi_hop",
    "use_entity_fallback",
    "budget_reason",
    "prompt_variant",
    "answer_shape",
    "steps",
)


def compare_activation_runs(
    off_rows: dict[str, dict],
    on_rows: dict[str, dict],
    *,
    allowed_route_change_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Compare paired runs keyed by case id."""
    allowed_route_change_ids = allowed_route_change_ids or set()
    common = [case_id for case_id in off_rows if case_id in on_rows]
    route_changed_ids = [
        case_id for case_id in common
        if _route_behavior(off_rows[case_id]) != _route_behavior(on_rows[case_id])
    ]
    ranked_key_changed_ids = [
        case_id for case_id in common
        if _ranked_keys(off_rows[case_id]) != _ranked_keys(on_rows[case_id])
    ]
    hit_changed_ids = [
        case_id for case_id in common
        if _hit_behavior(off_rows[case_id]) != _hit_behavior(on_rows[case_id])
    ]
    activatable_ids = [case_id for case_id in common if _activatable(on_rows[case_id])]
    activatable_set = set(activatable_ids)
    allowed_changed_ids = [
        case_id for case_id in route_changed_ids
        if case_id in allowed_route_change_ids and case_id not in activatable_set
    ]
    leak_ids = [
        case_id for case_id in route_changed_ids
        if case_id not in activatable_set and case_id not in allowed_route_change_ids
    ]
    hit_regression_ids = [
        case_id for case_id in common
        if _hit_regressed(_hit_behavior(off_rows[case_id]), _hit_behavior(on_rows[case_id]))
    ]
    return {
        "common": len(common),
        # Kept as the leak-relevant change set for Commit-1 callers/tests.
        "changed_ids": route_changed_ids,
        "route_changed_ids": route_changed_ids,
        "ranked_key_changed_ids": ranked_key_changed_ids,
        "hit_changed_ids": hit_changed_ids,
        "activatable_ids": activatable_ids,
        "allowed_route_change_ids": allowed_changed_ids,
        "leak_ids": leak_ids,
        "hit_regression_ids": hit_regression_ids,
        "gates": {
            "no_leak": len(leak_ids) == 0,
            "no_hit_regression": len(hit_regression_ids) == 0,
        },
    }


def _behavior(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ranked_keys": _ranked_keys(row),
        "hit_at_5": row.get("hit_at_5"),
        "hit_at_10": row.get("hit_at_10"),
        **_route_behavior(row),
    }


def _route_behavior(row: dict[str, Any]) -> dict[str, Any]:
    retrieval = row.get("retrieval_step") or {}
    plan = retrieval.get("query_plan") or {}
    trace = retrieval.get("routing_trace") or {}
    decision = trace.get("routing_decision") or {}
    prompt_policy = plan.get("prompt_policy") or {}
    fallback_policy = plan.get("fallback_policy") or {}
    return {
        "decision": (
            {field: decision.get(field) for field in _DECISION_FIELDS}
            if decision else {
                "use_hyde": plan.get("use_hyde"),
                "use_query_expansion": plan.get("use_query_expansion"),
                "use_multi_hop": plan.get("use_multi_hop"),
                "use_entity_fallback": fallback_policy.get("entity_filter_to_global"),
                "budget_reason": (plan.get("budget") or {}).get("reason"),
                "prompt_variant": prompt_policy.get("template"),
                "answer_shape": None,
                "steps": None,
            }
        ),
        "fallback_policy": fallback_policy,
        "retrieval_breadth": plan.get("retrieval_breadth"),
        "strict_evidence": plan.get("strict_evidence"),
        "budget": plan.get("budget"),
    }


def _ranked_keys(row: dict[str, Any]) -> list[str]:
    return [
        result.get("chunk_key") or result.get("document_id") or ""
        for result in row.get("rerank_results") or []
    ]


def _hit_behavior(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "hit_at_5": row.get("hit_at_5"),
        "hit_at_10": row.get("hit_at_10"),
    }


def _hit_regressed(off_hit: dict[str, Any], on_hit: dict[str, Any]) -> bool:
    for key in ("hit_at_5", "hit_at_10"):
        if off_hit.get(key) is True and on_hit.get(key) is False:
            return True
    return False


def _activatable(row: dict[str, Any]) -> bool:
    trace = (row.get("retrieval_step") or {}).get("routing_trace") or {}
    return bool((trace.get("inline_shadow") or {}).get("activatable_diverged"))


def _load_rows(path: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            rows[row["id"]] = row
    return rows


def main() -> None:
    args = _parse_args()
    summary = compare_activation_runs(
        _load_rows(args.off),
        _load_rows(args.on),
        allowed_route_change_ids=set(args.allowed_route_change_id),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["gates"]["no_leak"]:
        print(f"\nLEAK: non-activatable cases changed: {summary['leak_ids']}", file=sys.stderr)
        sys.exit(1)
    if not summary["gates"]["no_hit_regression"]:
        print(f"\nREGRESSION: retrieval hit dropped: {summary['hit_regression_ids']}", file=sys.stderr)
        sys.exit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare paired activation eval runs (2C-3 leak check)")
    parser.add_argument("--off", required=True, help="active-OFF retrieval_only results JSONL")
    parser.add_argument("--on", required=True, help="inline+active-ON retrieval_only results JSONL")
    parser.add_argument(
        "--allowed-route-change-id",
        action="append",
        default=[],
        help="Case id whose non-activatable route change is expected by a named migration",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
