"""Offline scorer for the Design 2C-1 routing golden set."""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
from typing import Any

from app.rag.query.config import QueryConfig
from app.rag.query.control.breadth import resolve_breadth
from app.rag.query.control.inferred import infer_signals, merge_intent
from app.rag.query.control.llm_classifier import classify_intent_llm
from app.rag.query.control.route_scoring import (
    aggregate,
    build_expected_intent,
    route_for_intent,
    score_case,
)
from app.rag.query.control.routing import decision_execution_dict, trust_gate


def _resolve_repo_root() -> Path:
    script_parent = Path(__file__).resolve().parent
    candidates = [
        script_parent.parent.parent,
        script_parent.parent,
        Path("/app"),
        Path.cwd(),
    ]
    for candidate in candidates:
        if (candidate / "data").is_dir():
            return candidate
    return Path(".")


REPO_ROOT = _resolve_repo_root()
DEFAULT_CORPUS = REPO_ROOT / "data" / "routing_golden_set_v1.jsonl"


def score_one(case: dict[str, Any]) -> dict[str, Any]:
    """Run one labeled case through the 2B pipeline and score the post-gate route."""
    breadth = _breadth_for(case)
    cfg = _cfg_for(case)
    det = infer_signals(case["query"], case["entity_mode"], case.get("matched_entities", []))
    expected = build_expected_intent(case["expected_intent"])
    if det.entity_scope != expected.entity_scope:
        raise ValueError(
            f"{case['id']}: deterministic scope {det.entity_scope!r} "
            f"!= expected scope {expected.entity_scope!r}"
        )

    llm = classify_intent_llm(case["query"], det)
    merged = merge_intent(det, llm)

    design1_decision = route_for_intent(det, breadth, cfg)
    merged_decision = route_for_intent(merged, breadth, cfg)
    expected_route = route_for_intent(expected, breadth, cfg)
    # The canonical trust gate requires high confidence and no classifier fallback.
    # Fallback outputs therefore score as the Design 1 safe-default route, which can
    # shift failure-case metrics compared with the older high-confidence-only gate.
    actual_route = trust_gate(merged, merged_decision, design1_decision)

    outcome = score_case(
        case["case_class"],
        bool(case.get("must_activate", False)),
        merged.confidence,
        actual=actual_route,
        expected=expected_route,
        design1=design1_decision,
    )
    det_outcome = score_case(
        case["case_class"],
        bool(case.get("must_activate", False)),
        det.confidence,
        actual=design1_decision,
        expected=expected_route,
        design1=design1_decision,
    )
    outcome.update({
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "retrieval_breadth": breadth,
        "case_class": case["case_class"],
        "must_activate": bool(case.get("must_activate", False)),
        "deterministic_route_correct": det_outcome["route_correct"],
        "fallback_used": merged.fallback_used,
        "deterministic": dataclasses.asdict(det),
        "merged": dataclasses.asdict(merged),
        "actual_execution": decision_execution_dict(actual_route),
        "expected_execution": decision_execution_dict(expected_route),
        "design1_execution": decision_execution_dict(design1_decision),
        "expected_markers": {
            key: value
            for key, value in case["expected_intent"].items()
            if key in ("needs_synthesis", "needs_discovery", "needs_multi_hop")
        },
        "merged_markers": {
            "needs_synthesis": merged.needs_synthesis,
            "needs_discovery": merged.needs_discovery,
            "needs_multi_hop": merged.needs_multi_hop,
        },
    })
    return outcome


def _cfg_for(case: dict[str, Any]) -> QueryConfig:
    return QueryConfig(
        strict_evidence=bool(case.get("strict_evidence", False)),
        use_hyde=bool(case.get("enable_hyde", True)),
        use_query_expansion=bool(case.get("enable_query_expansion", True)),
        use_multi_hop=bool(case.get("enable_multi_hop", True)),
    )


def _breadth_for(case: dict[str, Any]) -> str:
    breadth = case.get("retrieval_breadth")
    if breadth:
        return str(breadth)
    return resolve_breadth(str(case.get("retrieval_flavor") or "balanced"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    args = _parse_args()
    corpus = Path(args.corpus)
    rows = [score_one(case) for case in _load_jsonl(corpus)]
    summary = aggregate(rows)
    summary["fallback_rate"] = (
        round(sum(1 for row in rows if row["fallback_used"]) / len(rows), 4) if rows else 0.0
    )

    output = Path(args.output or (REPO_ROOT / "data" / "routing_golden_set_v1_scored.jsonl"))
    _write_jsonl(output, rows)
    summary_path = output.with_name(f"{output.stem}_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Results saved to {output}")
    print(f"Summary saved to {summary_path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score the 2C-1 routing golden set")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS), help="Routing golden set JSONL")
    parser.add_argument("--output", default=None, help="Output JSONL path")
    return parser.parse_args()


if __name__ == "__main__":
    main()
